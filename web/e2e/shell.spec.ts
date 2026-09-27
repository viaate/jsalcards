/**
 * The app shell: first paint before any script, the swap to the Svelte shell,
 * the lazy MapLibre takeover, the initial view and the attribution control.
 *
 * Every test opens its own browser context at the viewports the shell is
 * judged at, so they run once, under the desktop project.
 *
 * WebGL here runs on SwiftShader (software). Pixel checks compare where lines
 * are, not how fast they appear.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext, Page, Request, Route } from '@playwright/test';
import sharp from 'sharp';

import { STATUS_KEYS, copy } from '../src/copy';
import { BASEMAP_IDS } from '../src/map/basemap/ids';
import { STILL_VIEWBOX, US_BOUNDS, US_LINES_GZIP_BYTES } from '../src/map/basemap/us-geo';

const WEB = fileURLToPath(new URL('..', import.meta.url));

interface Viewport {
  name: string;
  width: number;
  height: number;
  deviceScaleFactor: number;
  isMobile: boolean;
}

const DESKTOP: Viewport = {
  name: 'desktop 1440x900',
  width: 1440,
  height: 900,
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

/** The basemap code's chunk. The map cannot start without it. */
const MAP_CHUNK = /\/assets\/basemap-[\w-]+\.js$/;
/** MapLibre's shared module, which the page and MapLibre's workers both import. */
const SHARED_CHUNK = /\/assets\/maplibre-shared-[\w-]+\.js$/;
/**
 * Everything the map downloads after first paint, by name without the content
 * hash: the basemap code, MapLibre's page module, its shared module, its
 * worker's source, the street tile code its workers import, and the bundled
 * US lines.
 */
const MAP_DOWNLOADS = [
  'basemap',
  'maplibre',
  'maplibre-shared',
  'maplibre-worker',
  'street-tiles',
  'us-lines',
] as const;
/** MapLibre's scripts, gzipped at zlib's default level, as a static host serves them. */
const MAPLIBRE_GZIP_BUDGET = 310_000;
/** A name only MapLibre's shared module defines: each script containing it is a copy. */
const SHARED_MODULE_MARKER = 'REGISTERED_PROTOCOLS';

/** "assets/maplibre-shared-AbCd1234.js" -> "maplibre-shared"; "geo/us-lines.1a2b.json" -> "us-lines". */
function downloadName(url: string): string | null {
  const { pathname } = new URL(url);
  const asset = /\/assets\/(.+)-[\w-]{8}\.js$/.exec(pathname);
  if (asset !== null) return asset[1] ?? null;
  const geo = /\/geo\/([\w-]+)\.[0-9a-f]+\.json$/.exec(pathname);
  return geo?.[1] ?? null;
}
/**
 * Console lines Chrome itself prints because this machine has no GPU and WebGL
 * runs on SwiftShader. They come from the browser, not from the page.
 */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

async function newContext(
  browser: Browser,
  viewport: Viewport,
  options: { javaScriptEnabled?: boolean; serviceWorkers?: 'allow' | 'block' } = {},
): Promise<BrowserContext> {
  return browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.deviceScaleFactor,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    javaScriptEnabled: options.javaScriptEnabled ?? true,
    serviceWorkers: options.serviceWorkers ?? 'allow',
  });
}

/** Records console errors and warnings, page errors, failed and foreign requests. */
function watch(page: Page, origin: string): { problems: string[]; foreign: string[] } {
  const problems: string[] = [];
  const foreign: string[] = [];
  page.on('console', (message) => {
    const type = message.type();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(message.text())) {
      problems.push(`console.${type}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => problems.push(`requestfailed: ${request.url()}`));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
    }
  });
  page.on('request', (request: Request) => {
    const url = new URL(request.url());
    if (url.protocol !== 'data:' && url.origin !== origin) foreign.push(request.url());
  });
  return { problems, foreign };
}

/** Holds matching requests until release() is called. */
async function hold(
  page: Page,
  pattern: RegExp,
): Promise<{ release: () => void; held: Promise<void> }> {
  let release = (): void => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let markHeld = (): void => undefined;
  const held = new Promise<void>((resolve) => {
    markHeld = resolve;
  });
  await page.route(pattern, async (route: Route) => {
    markHeld();
    await gate;
    await route.continue().catch(() => undefined);
  });
  return { release, held };
}

/** The city names MapLibre placed at the national view, from every band's layer. */
async function cityNames(page: Page): Promise<string[]> {
  return page.evaluate((prefix) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const layers = map
      .getStyle()
      .layers.map((layer) => layer.id)
      .filter((id) => id.startsWith(prefix));
    return map.queryRenderedFeatures({ layers }).flatMap((feature) => {
      const name: unknown = (feature.properties as Record<string, unknown>).name;
      return typeof name === 'string' ? [name] : [];
    });
  }, BASEMAP_IDS.usCityLabel);
}

/** The state names MapLibre placed (a phone's map names the states), from every state's layer. */
async function stateNames(page: Page): Promise<string[]> {
  return page.evaluate((prefix) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const layers = map
      .getStyle()
      .layers.map((layer) => layer.id)
      .filter((id) => id.startsWith(prefix));
    return map.queryRenderedFeatures({ layers }).flatMap((feature) => {
      const name: unknown = (feature.properties as Record<string, unknown>).name;
      return typeof name === 'string' ? [name] : [];
    });
  }, BASEMAP_IDS.usStateLabel);
}

/**
 * Hides the city and state names, which the still does not carry, and waits
 * for the map to draw without them: what is left is the land and its lines.
 */
async function hideCityNames(page: Page): Promise<void> {
  await page.evaluate(
    (prefixes) =>
      new Promise<void>((resolve) => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        for (const layer of map.getStyle().layers) {
          if (prefixes.some((prefix) => layer.id.startsWith(prefix))) {
            map.setLayoutProperty(layer.id, 'visibility', 'none');
          }
        }
        map.once('idle', () => {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              resolve();
            });
          });
        });
        map.triggerRepaint();
      }),
    [BASEMAP_IDS.usCityLabel, BASEMAP_IDS.usStateLabel],
  );
}

/** Waits until the map has drawn everything it has asked for, the city names too. */
async function whenIdle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const map = window.snowlightMap;
        if (map?.loaded() !== false) {
          resolve();
          return;
        }
        map.once('idle', () => {
          resolve();
        });
      }),
  );
}

async function waitForTakeover(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 30_000,
  });
  // Let the canvas frame that replaced the still reach the screen.
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

interface Gray {
  data: Uint8Array;
  width: number;
  height: number;
}

async function gray(png: Buffer): Promise<Gray> {
  const { data, info } = await sharp(png)
    .removeAlpha()
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return { data: new Uint8Array(data), width: info.width, height: info.height };
}

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Device-pixel rectangle, clamped to the image. */
function deviceRect(
  box: Box,
  scale: number,
  image: Gray,
  pad = 0,
): [number, number, number, number] {
  return [
    Math.max(0, Math.floor((box.x - pad) * scale)),
    Math.max(0, Math.floor((box.y - pad) * scale)),
    Math.min(image.width, Math.ceil((box.x + box.width + pad) * scale)),
    Math.min(image.height, Math.ceil((box.y + box.height + pad) * scale)),
  ];
}

interface LineComparison {
  pixels: [number, number];
  coverage: [number, number];
  bestShift: [number, number];
  meanAbsDiff: number;
}

/**
 * Compares the line pixels of two screenshots inside `region`, ignoring
 * `exclude`. Coverage is the share of line pixels in one image with a line
 * pixel within one device pixel in the other; bestShift is the offset that
 * best lines the two up.
 */
function compareLines(
  a: Gray,
  b: Gray,
  region: [number, number, number, number],
  exclude: [number, number, number, number] | null,
  threshold = 24,
): LineComparison {
  const [x0, y0, x1, y1] = region;
  const { width } = a;
  const inside = (x: number, y: number): boolean =>
    exclude === null || x < exclude[0] || x >= exclude[2] || y < exclude[1] || y >= exclude[3];
  const at = (image: Gray, x: number, y: number): number => image.data[y * width + x] ?? 0;

  const covered = (p: Gray, q: Gray): [number, number] => {
    let lines = 0;
    let hits = 0;
    for (let y = y0 + 1; y < y1 - 1; y++) {
      for (let x = x0 + 1; x < x1 - 1; x++) {
        if (!inside(x, y) || at(p, x, y) <= threshold) continue;
        lines++;
        search: for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (at(q, x + dx, y + dy) > threshold / 2) {
              hits++;
              break search;
            }
          }
        }
      }
    }
    return [lines, lines === 0 ? 0 : hits / lines];
  };

  let best: [number, number] = [0, 0];
  let bestScore = -Infinity;
  for (let dy = -3; dy <= 3; dy++) {
    for (let dx = -3; dx <= 3; dx++) {
      let score = 0;
      for (let y = y0 + 3; y < y1 - 3; y++) {
        for (let x = x0 + 3; x < x1 - 3; x++) {
          if (inside(x, y)) score += at(a, x, y) * at(b, x + dx, y + dy);
        }
      }
      if (score > bestScore) {
        bestScore = score;
        best = [dx, dy];
      }
    }
  }

  let diff = 0;
  let count = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if (!inside(x, y)) continue;
      diff += Math.abs(at(a, x, y) - at(b, x, y));
      count++;
    }
  }

  const [linesA, coverA] = covered(a, b);
  const [linesB, coverB] = covered(b, a);
  return {
    pixels: [linesA, linesB],
    coverage: [coverA, coverB],
    bestShift: best,
    meanAbsDiff: count === 0 ? 0 : diff / count,
  };
}

/** Bounding box, in CSS pixels, of the pixels brighter than `threshold` inside `region`. */
function litBounds(
  image: Gray,
  scale: number,
  region: [number, number, number, number],
  threshold = 24,
): Box {
  const [x0, y0, x1, y1] = region;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if ((image.data[y * image.width + x] ?? 0) > threshold) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }
  return {
    x: minX / scale,
    y: minY / scale,
    width: (maxX - minX + 1) / scale,
    height: (maxY - minY + 1) / scale,
  };
}

async function box(page: Page, selector: string): Promise<Box> {
  const found = await page.locator(selector).first().boundingBox();
  if (found === null) throw new Error(`${selector} has no box`);
  return found;
}

test.describe('first paint, before any script', () => {
  for (const viewport of VIEWPORTS) {
    test(`paints the ground, outline, search pill and wordmark with no JavaScript (${viewport.name})`, async ({
      browser,
      baseURL,
    }) => {
      const context = await newContext(browser, viewport, { javaScriptEnabled: false });
      const page = await context.newPage();
      const origin = new URL(baseURL ?? '').origin;
      const { problems, foreign } = watch(page, origin);
      await page.goto('/', { waitUntil: 'load' });

      expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
        'rgb(0, 0, 0)',
      );
      await expect(page.locator('h1.wordmark')).toHaveText(copy.appName);
      await expect(page.locator('input.search-input')).toHaveAttribute(
        'placeholder',
        copy.search.placeholder,
      );
      await expect(page.locator('input.search-input')).toHaveAttribute(
        'aria-label',
        copy.search.placeholder,
      );
      await expect(page.locator('svg.still path')).toHaveCount(2);

      const frame = await box(page, '.frame');
      const still = await box(page, 'svg.still');
      const shot = await gray(await page.screenshot());
      const bar = await box(page, '.bar');
      if (!viewport.isMobile) {
        // The still fills the frame, and the US lines fill the still on its limiting axis.
        expect(still).toEqual(frame);
        const region = deviceRect(frame, viewport.deviceScaleFactor, shot, 2);
        const lit = litBounds(shot, viewport.deviceScaleFactor, region);
        const slackX = frame.width - lit.width;
        const slackY = frame.height - lit.height;
        expect(Math.min(slackX, slackY)).toBeLessThanOrEqual(3);
        expect(Math.abs(lit.x - frame.x - slackX / 2)).toBeLessThanOrEqual(2);
        expect(Math.abs(lit.y - frame.y - slackY / 2)).toBeLessThanOrEqual(2);

        // Sensible padding: clear of the search pill, off the screen edges.
        expect(lit.y).toBeGreaterThanOrEqual(bar.y + bar.height + 12);
        expect(lit.x).toBeGreaterThanOrEqual(12);
        expect(viewport.width - (lit.x + lit.width)).toBeGreaterThanOrEqual(12);
        expect(viewport.height - (lit.y + lit.height)).toBeGreaterThanOrEqual(16);
        // And the US is as large as that padding allows: most of the width.
        expect(lit.width / viewport.width).toBeGreaterThan(0.75);
      } else {
        // A phone held upright: the still fills the frame's height and runs off both its sides,
        // placed --home-focus of the way across (the rest of the world's here: no script ran).
        const focus = await page.evaluate(() =>
          Number.parseFloat(
            getComputedStyle(document.documentElement).getPropertyValue('--home-focus'),
          ),
        );
        expect(focus).toBe(0.5);
        const [, , viewWidth = NaN, viewHeight = NaN] = STILL_VIEWBOX.split(' ').map(Number);
        expect(Math.abs(still.height - frame.height)).toBeLessThan(0.5);
        expect(Math.abs(still.width - (frame.height * viewWidth) / viewHeight)).toBeLessThan(0.5);
        expect(Math.abs(still.y - frame.y)).toBeLessThan(0.5);
        expect(Math.abs(still.x - frame.x - focus * (frame.width - still.width))).toBeLessThan(0.5);
        // The land runs from one side of the screen to the other, and from under the search
        // pill to the key: the northern border to the Rio Grande.
        const band = { x: 0, y: frame.y, width: viewport.width, height: frame.height };
        const lit = litBounds(
          shot,
          viewport.deviceScaleFactor,
          deviceRect(band, viewport.deviceScaleFactor, shot),
        );
        expect(lit.x).toBeLessThanOrEqual(1);
        expect(lit.x + lit.width).toBeGreaterThanOrEqual(viewport.width - 1);
        expect(lit.y + lit.height).toBeGreaterThan(frame.y + frame.height - 48);
        expect(lit.height / frame.height).toBeGreaterThan(0.9);
        expect(lit.y).toBeGreaterThanOrEqual(bar.y + bar.height + 12);
      }

      // Nothing shown is data: no counts, times or statuses before anything has loaded. The
      // legend names the four statuses as a key, in code order, and nothing else names one.
      const legend = page.locator('ul.legend');
      await expect(legend).toHaveAttribute('aria-label', copy.legend.label);
      await expect(legend.locator('li')).toHaveText(STATUS_KEYS.map((key) => copy.status[key]));
      const text = await page.evaluate(() => document.body.innerText);
      expect(text).not.toMatch(/\d/);
      const rest = await page.evaluate(() => {
        const copyOf = document.body.cloneNode(true) as HTMLElement;
        copyOf.querySelector('ul.legend')?.remove();
        return copyOf.textContent;
      });
      for (const status of Object.values(copy.status)) expect(rest).not.toContain(status);

      expect(problems).toEqual([]);
      expect(foreign).toEqual([]);
      await context.close();
    });
  }

  test('lays a phone out for a thumb: name, a full-width field, the country, the key', async ({
    browser,
  }) => {
    const SMALL_PHONE: Viewport = {
      name: 'small phone 320x568',
      width: 320,
      height: 568,
      deviceScaleFactor: 2,
      isMobile: true,
    };
    for (const viewport of [PHONE, SMALL_PHONE]) {
      const context = await newContext(browser, viewport, { javaScriptEnabled: false });
      const page = await context.newPage();
      await page.goto('/', { waitUntil: 'load' });
      const where = viewport.name;

      // The wordmark on a line of its own, and under it the field from edge to edge.
      const name = await box(page, 'h1.wordmark');
      const field = await box(page, '.search');
      expect(name.x, where).toBe(16);
      expect(name.y + name.height, where).toBeLessThanOrEqual(field.y - 8);
      expect(field.x, where).toBe(16);
      expect(field.x + field.width, where).toBe(viewport.width - 16);
      expect(field.height, where).toBeGreaterThanOrEqual(48);

      // The key sits at the foot of the screen, clear of the attribution's corner: one line
      // where it fits, two tidy lines of two on the narrowest phones.
      const legend = await box(page, 'ul.legend');
      expect(legend.x, where).toBe(16);
      expect(viewport.height - (legend.y + legend.height), where).toBe(16);
      expect(legend.x + legend.width, where).toBeLessThanOrEqual(viewport.width - 16 - 28 - 8);
      const keys = await page
        .locator('ul.legend li')
        .evaluateAll((items) =>
          items.map((item) => Math.round(item.getBoundingClientRect().top * 10) / 10),
        );
      const lines = [...new Set(keys)];
      if (viewport.width >= 375) expect(lines, where).toHaveLength(1);
      else expect(keys, where).toEqual([lines[0], lines[0], lines[1], lines[1]]);

      // The country fills the screen between the field and the key: the frame starts as far
      // under the field as it ends over the key, and the still fills its height, edge to edge.
      const frame = await box(page, '.frame');
      const still = await box(page, 'svg.still');
      const above = frame.y - (field.y + field.height);
      const below = legend.y - (frame.y + frame.height);
      expect(above, where).toBe(24);
      // The narrowest phones' key takes two lines, and part of the gap under the frame.
      expect(below, where).toBeGreaterThanOrEqual(viewport.width >= 375 ? 24 : 12);
      expect(Math.abs(still.height - frame.height), where).toBeLessThan(0.5);
      expect(still.x, where).toBeLessThanOrEqual(0);
      expect(still.x + still.width, where).toBeGreaterThanOrEqual(viewport.width);

      // A button that takes the map to the phone's own area, a thumb's reach above the
      // attribution's corner: named, and big enough to press.
      const locate = page.locator('button.locate');
      await expect(locate).toBeVisible();
      await expect(locate).toHaveAttribute('aria-label', copy.map.locate);
      const button = await box(page, 'button.locate');
      expect(button.width, where).toBeGreaterThanOrEqual(48);
      expect(button.height, where).toBeGreaterThanOrEqual(48);
      expect(viewport.width - (button.x + button.width), where).toBe(16);
      // Clear of the key and of the attribution's corner under it.
      const apart = (a: Box, b: Box): boolean =>
        a.x + a.width <= b.x ||
        b.x + b.width <= a.x ||
        a.y + a.height <= b.y ||
        b.y + b.height <= a.y;
      expect(apart(button, legend), where).toBe(true);
      expect(viewport.height - (button.y + button.height), where).toBeGreaterThanOrEqual(
        16 + 28 + 8,
      );
      await context.close();
    }
  });

  test('links no render-blocking stylesheet and never lets the font block paint', async ({
    browser,
    request,
  }) => {
    const html = await (await request.get('/')).text();
    expect(html).not.toMatch(/<link[^>]+rel="stylesheet"/);
    expect(html).toMatch(/<link[^>]+rel="preload"[^>]+as="font"/);
    expect(html).toMatch(/font-display:\s*swap/);
    expect(html).not.toMatch(/fonts\.googleapis|fonts\.gstatic/);

    // Hold the font for three seconds: text still paints at once, in the fallback face.
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    await page.route(/\.woff2$/, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3000));
      await route.continue().catch(() => undefined);
    });
    await page.goto('/', { waitUntil: 'commit' });
    await page.waitForFunction(
      () => performance.getEntriesByName('first-contentful-paint').length > 0,
      null,
      { timeout: 2000 },
    );
    const fcp = await page.evaluate(
      () => performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? Infinity,
    );
    expect(fcp).toBeLessThan(1000);
    await context.close();
  });
});

test.describe('handover to the WebGL map', () => {
  for (const viewport of VIEWPORTS) {
    test(`the outline does not move when MapLibre takes over (${viewport.name})`, async ({
      browser,
      baseURL,
    }) => {
      const origin = new URL(baseURL ?? '').origin;

      // Reference: the page as painted with no script at all.
      const staticContext = await newContext(browser, viewport, { javaScriptEnabled: false });
      const staticPage = await staticContext.newPage();
      await staticPage.goto('/', { waitUntil: 'load' });
      const painted = await gray(await staticPage.screenshot());
      await staticContext.close();

      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      const { problems, foreign } = watch(page, origin);
      await page.addInitScript(() => {
        const shifts: number[] = [];
        (window as unknown as { __shifts: number[] }).__shifts = shifts;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            shifts.push((entry as unknown as { value: number }).value);
          }
        }).observe({ type: 'layout-shift', buffered: true });
      });
      const mapChunk = await hold(page, MAP_CHUNK);
      await page.goto('/', { waitUntil: 'load' });
      await mapChunk.held;

      // Before: the Svelte shell has replaced the static one; the map code is still loading.
      await expect(page.locator('main.stage')).toHaveCount(1);
      await expect(page.locator('[data-static-shell]')).toHaveCount(0);
      await expect(page.locator('svg.still')).toHaveCount(1);
      const before = await gray(await page.screenshot());

      mapChunk.release();
      await waitForTakeover(page);
      await expect(page.locator('.maplibregl-canvas')).toBeVisible();
      // The map names the largest cities, the whole country's on a desktop and its part of it
      // on a phone held upright, once its first frame is up; the still carries none.
      await whenIdle(page);
      const named = await cityNames(page);
      if (viewport.isMobile) expect(named.length).toBeGreaterThanOrEqual(6);
      else expect(named.length).toBeGreaterThan(10);
      await hideCityNames(page);
      const after = await gray(await page.screenshot());

      const scale = viewport.deviceScaleFactor;
      const frame = await box(page, '.frame');
      const attribution = await box(page, '.maplibregl-ctrl-attrib');
      const region = deviceRect(frame, scale, after, 4);
      const exclude = deviceRect(attribution, scale, after, 2);

      // The swap from the static shell to the Svelte shell is invisible.
      const swap = compareLines(painted, before, [0, 0, before.width, before.height], null);
      expect(swap.meanAbsDiff).toBeLessThan(0.05);

      // The WebGL lines sit on the still's lines.
      const handover = compareLines(before, after, region, exclude);
      test.info().annotations.push({
        type: 'handover',
        description: JSON.stringify(handover),
      });
      expect(handover.pixels[0]).toBeGreaterThan(1000);
      expect(handover.coverage[0]).toBeGreaterThanOrEqual(0.99);
      expect(handover.coverage[1]).toBeGreaterThanOrEqual(0.99);
      expect(handover.bestShift).toEqual([0, 0]);
      expect(handover.meanAbsDiff).toBeLessThan(1.5);

      // The chrome above the map does not change at all.
      const bar = await box(page, '.bar');
      const barRegion = deviceRect(bar, scale, after, 4);
      expect(compareLines(before, after, barRegion, null).meanAbsDiff).toBeLessThan(0.05);

      const shifts = await page.evaluate(
        () => (window as unknown as { __shifts: number[] }).__shifts,
      );
      expect(shifts.reduce((sum, value) => sum + value, 0)).toBe(0);
      expect(problems).toEqual([]);
      expect(foreign).toEqual([]);
      await context.close();
    });
  }

  test('loads MapLibre after first paint, through a dynamic import', async ({
    browser,
    request,
  }) => {
    const html = await (await request.get('/')).text();
    expect(html).not.toMatch(/basemap-|maplibre/);
    const entry = /<script type="module" crossorigin src="([^"]+)"/.exec(html)?.[1];
    expect(entry).toBeDefined();
    const entryJs = await (await request.get(entry ?? '')).text();
    // MapLibre alone is about 800 kB. The entry is the shell, Svelte and the copy module,
    // whose formatters (the update time's among them) come with it wherever they are used.
    expect(entryJs.length).toBeLessThan(75_000);
    expect(entryJs).not.toMatch(/maplibregl-/);

    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    await page.goto('/');
    await waitForTakeover(page);
    const timing = await page.evaluate(() => {
      const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? Infinity;
      const chunk = performance
        .getEntriesByType('resource')
        .find((entry) => /\/assets\/basemap-[\w-]+\.js$/.test(entry.name));
      return { fcp, chunkStart: chunk?.startTime ?? -1 };
    });
    expect(timing.chunkStart).toBeGreaterThan(timing.fcp);
    await context.close();
  });

  test('starts every map download at once and waits on none of them', async ({ browser }) => {
    const context = await newContext(browser, PHONE);
    const page = await context.newPage();
    const requested = new Set<string>();
    const mapDownloads: readonly (string | null)[] = MAP_DOWNLOADS;
    context.on('request', (request) => {
      const name = downloadName(request.url());
      if (mapDownloads.includes(name)) requested.add(name ?? '');
    });
    // Hold the largest file. Anything that only starts once another download has
    // finished (the worker, the US lines) would then never be requested.
    const shared = await hold(page, SHARED_CHUNK);
    await page.goto('/');
    await shared.held;
    await expect
      .poll(() => [...requested].sort(), { timeout: 10_000 })
      .toEqual([...MAP_DOWNLOADS].sort());
    await expect(page.locator('svg.still')).toHaveCount(1);
    shared.release();
    await waitForTakeover(page);

    // And none of them was requested before the first paint.
    const timing = await page.evaluate(() => ({
      fcp: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? Infinity,
      starts: performance
        .getEntriesByType('resource')
        .filter((entry) =>
          /\/(assets|geo)\/(basemap|maplibre|street-tiles|us-lines)/.test(entry.name),
        )
        .map((entry) => entry.startTime),
    }));
    expect(timing.starts.length).toBeGreaterThanOrEqual(MAP_DOWNLOADS.length);
    for (const start of timing.starts) expect(start).toBeGreaterThan(timing.fcp);
    await context.close();
  });

  test('downloads MapLibre once, shared by the page and its workers, within budget', async ({
    browser,
  }) => {
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    // Every script body that came over the network, page and workers alike, by path.
    const bodies = new Map<string, Promise<Buffer | null>>();
    context.on('response', (response) => {
      const { pathname } = new URL(response.url());
      if (!/\/assets\/[^/]+\.js$/.test(pathname)) return;
      if (response.status() !== 200 || bodies.has(pathname)) return;
      bodies.set(
        pathname,
        response.body().catch(() => null),
      );
    });
    await page.goto('/');
    await waitForTakeover(page);

    // MapLibre's workers run, started from the page's copy, not from a bundle of their own.
    const workers = page.workers();
    expect(workers.length).toBeGreaterThan(0);
    for (const worker of workers) expect(worker.url()).toMatch(/^blob:/);

    const scripts: { path: string; name: string | null; gzipBytes: number; shared: boolean }[] = [];
    for (const [path, body] of bodies) {
      const code = await body;
      expect(code, path).not.toBeNull();
      if (code === null) continue;
      scripts.push({
        path,
        name: downloadName(`http://localhost${path}`),
        gzipBytes: gzipSync(code).length,
        shared: code.includes(SHARED_MODULE_MARKER),
      });
    }
    const map = scripts.filter((script) =>
      (MAP_DOWNLOADS as readonly (string | null)[]).includes(script.name),
    );
    test.info().annotations.push({ type: 'map scripts', description: JSON.stringify(map) });

    // Each of the map's scripts once.
    expect(map.map((script) => script.name).sort()).toEqual(
      MAP_DOWNLOADS.filter((name) => name !== 'us-lines').sort(),
    );
    // One copy of MapLibre's shared module among every script loaded, page and workers alike.
    const copies = scripts.filter((script) => script.shared);
    expect(copies.map((script) => script.name)).toEqual(['maplibre-shared']);
    // MapLibre's own scripts stay within budget.
    const maplibre = map.filter((script) => script.name?.startsWith('maplibre') === true);
    expect(maplibre).toHaveLength(3);
    const total = maplibre.reduce((sum, script) => sum + script.gzipBytes, 0);
    expect(total).toBeLessThanOrEqual(MAPLIBRE_GZIP_BUDGET);
    await context.close();
  });

  test('keeps a typed search across the swap to the Svelte shell', async ({ browser }) => {
    const context = await newContext(browser, DESKTOP);
    const page = await context.newPage();
    const entry = await hold(page, /\/(assets\/index-[\w-]+\.js|src\/main\.ts)$/);
    // DOMContentLoaded waits for the held module script, so only wait for the response.
    await page.goto('/', { waitUntil: 'commit' });
    await entry.held;
    await page.locator('[data-static-shell] input.search-input').fill('Duluth');
    await page.locator('[data-static-shell] input.search-input').focus();
    entry.release();
    await expect(page.locator('[data-static-shell]')).toHaveCount(0);
    const live = page.locator('input.search-input');
    await expect(live).toHaveValue('Duluth');
    await expect(live).toBeFocused();
    // Enter stays on the page: the live shell does not submit the form.
    const url = page.url();
    await live.press('Enter');
    await page.waitForTimeout(300);
    expect(page.url()).toBe(url);
    await expect(live).toHaveValue('Duluth');
    await context.close();
  });
});

test.describe('the map at rest', () => {
  test('names a few dozen of the largest cities over black land, none on another', async ({
    browser,
  }) => {
    const TABLET: Viewport = {
      name: 'tablet 820x1180',
      width: 820,
      height: 1180,
      deviceScaleFactor: 2,
      isMobile: true,
    };
    // The largest cities each screen names: a tablet has room for New York or Washington, not both.
    const LARGEST = ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Seattle'];
    for (const [viewport, fewest, most, named] of [
      [DESKTOP, 24, 40, [...LARGEST, 'Washington', 'Boston', 'Atlanta']],
      [TABLET, 8, 16, LARGEST],
    ] as const) {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      await whenIdle(page);
      const names = await cityNames(page);
      test.info().annotations.push({ type: viewport.name, description: names.join(', ') });
      expect(names.length, viewport.name).toBeGreaterThanOrEqual(fewest);
      expect(names.length, viewport.name).toBeLessThanOrEqual(most);
      expect(new Set(names).size, viewport.name).toBe(names.length);
      for (const city of named) expect(names, `${viewport.name}: ${city}`).toContain(city);
      // Each name keeps clear of the others: their boxes, as MapLibre placed them, never meet.
      const boxes = await page.evaluate((prefix) => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        const layers = map
          .getStyle()
          .layers.map((layer) => layer.id)
          .filter((id) => id.startsWith(prefix));
        return map.queryRenderedFeatures({ layers }).map((feature) => {
          const { coordinates } = feature.geometry as unknown as { coordinates: [number, number] };
          const point = map.project(coordinates);
          return {
            x: point.x,
            y: point.y,
            name: String((feature.properties as { name?: unknown }).name),
          };
        });
      }, BASEMAP_IDS.usCityLabel);
      for (const [i, a] of boxes.entries()) {
        for (const b of boxes.slice(i + 1)) {
          const apart = Math.abs(a.x - b.x) > 40 || Math.abs(a.y - b.y) > 14;
          expect(apart, `${a.name} and ${b.name}`).toBe(true);
        }
      }
      // The land is the ground's own black (the owner's call): only lines and names are lit.
      const shot = await gray(await page.screenshot());
      const inland = await page.evaluate(() => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        // Central Nebraska, clear of every line and name.
        const point = map.project([-99.9, 41.95]);
        return { x: Math.round(point.x), y: Math.round(point.y) };
      });
      const at = (x: number, y: number): number =>
        shot.data[
          Math.round(y * viewport.deviceScaleFactor) * shot.width +
            Math.round(x * viewport.deviceScaleFactor)
        ] ?? -1;
      expect(at(inland.x, inland.y)).toBe(0);
      expect(at(4, viewport.height - 4)).toBe(0);
      await context.close();
    }
  });

  test("a phone opens on its own part of the country, by time zone, no name cut by the screen's edges", async ({
    browser,
  }) => {
    // Five maps load one after another: longer than one test's usual time.
    test.setTimeout(120_000);
    // Longitudes each home view takes in, whole, on a 390 x 844 phone, and a point of open
    // country in it, clear of every line and name.
    const ZONES: [zone: string | undefined, west: number, east: number, land: [number, number]][] =
      [
        // The rest of the world: the middle of the country, Kansas City in the middle.
        [undefined, -100, -87.7, [-99.5, 39.3]],
        ['America/New_York', -84.4, -71.1, [-74.5, 44]],
        ['America/Chicago', -100, -87.7, [-99.5, 39.3]],
        ['America/Denver', -112, -104.9, [-110.5, 43]],
        ['America/Los_Angeles', -124.7, -118.2, [-120.5, 44]],
      ];
    for (const [zone, west, east, open] of ZONES) {
      const where = zone ?? 'UTC';
      const context = await browser.newContext({
        viewport: { width: PHONE.width, height: PHONE.height },
        deviceScaleFactor: PHONE.deviceScaleFactor,
        isMobile: true,
        hasTouch: true,
        ...(zone === undefined ? {} : { timezoneId: zone }),
      });
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      await whenIdle(page);
      // The home view: no view in the address, and the screen from `west` to `east` at least.
      expect(new URL(page.url()).search, where).toBe('');
      const shown = await page.evaluate(() => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        const bounds = map.getBounds();
        return { west: bounds.getWest(), east: bounds.getEast(), zoom: map.getZoom() };
      });
      expect(shown.west, where).toBeLessThan(west);
      expect(shown.east, where).toBeGreaterThan(east);
      expect(shown.zoom, where).toBeGreaterThan(3.5);
      const named = await cityNames(page);
      expect(named.length, where).toBeGreaterThanOrEqual(4);
      // And the states are named, in capitals under the city names, each once.
      const states = await stateNames(page);
      expect(states.length, where).toBeGreaterThanOrEqual(5);
      expect(new Set(states).size, where).toBe(states.length);

      // The land is the ground's black on a phone too (the owner's call), clear of every line and name.
      const shot = await gray(await page.screenshot());
      const land = await page.evaluate(([lon, lat]) => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        const point = map.project([lon, lat]);
        return { x: Math.round(point.x), y: Math.round(point.y) };
      }, open);
      const scale = PHONE.deviceScaleFactor;
      const at = (x: number, y: number): number =>
        shot.data[Math.round(y * scale) * shot.width + Math.round(x * scale)] ?? -1;
      const ground = at(land.x, land.y);
      expect(ground, where).toBe(0);

      // What the names add to the picture never touches the screen's sides: none is cut there.
      await hideCityNames(page);
      const bare = await gray(await page.screenshot());
      let touching = 0;
      for (let y = 0; y < shot.height; y++) {
        for (const x of [0, 1, shot.width - 2, shot.width - 1]) {
          const i = y * shot.width + x;
          if (Math.abs((shot.data[i] ?? 0) - (bare.data[i] ?? 0)) > 24) touching++;
        }
      }
      expect(touching, where).toBe(0);
      await context.close();
    }
  });

  test('a phone names the states, clear of the city names; a wider screen names none', async ({
    browser,
  }) => {
    for (const viewport of [PHONE, DESKTOP]) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: viewport.deviceScaleFactor,
        isMobile: viewport.isMobile,
        hasTouch: viewport.isMobile,
        timezoneId: 'UTC',
      });
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      await whenIdle(page);
      const states = await stateNames(page);
      test.info().annotations.push({ type: viewport.name, description: states.join(', ') });
      if (!viewport.isMobile) {
        expect(states, viewport.name).toEqual([]);
        await context.close();
        continue;
      }
      // The middle of the country, named state by state around Kansas City.
      for (const state of ['Kansas', 'Nebraska', 'Iowa', 'Missouri', 'Oklahoma', 'Arkansas']) {
        expect(states, state).toContain(state);
      }
      // Each state name keeps clear of every city name: their middles are never close.
      const points = await page.evaluate(
        (prefixes) => {
          const map = window.snowlightMap;
          if (map === undefined) throw new Error('no map');
          const layers = map
            .getStyle()
            .layers.map((layer) => layer.id)
            .filter((id) => prefixes.some((prefix) => id.startsWith(prefix)));
          return map.queryRenderedFeatures({ layers }).map((feature) => {
            const { coordinates } = feature.geometry as unknown as {
              coordinates: [number, number];
            };
            const point = map.project(coordinates);
            const { kind, name } = feature.properties as { kind?: unknown; name?: unknown };
            return { x: point.x, y: point.y, kind: String(kind), name: String(name) };
          });
        },
        [BASEMAP_IDS.usCityLabel, BASEMAP_IDS.usStateLabel],
      );
      const cities = points.filter((point) => point.kind === 'city');
      for (const state of points.filter((point) => point.kind === 'state-name')) {
        for (const city of cities) {
          const apart = Math.abs(state.x - city.x) > 60 || Math.abs(state.y - city.y) > 16;
          expect(apart, `${state.name} and ${city.name}`).toBe(true);
        }
      }
      await context.close();
    }
  });

  test('the attribution is a small collapsed button in the bottom corner', async ({ browser }) => {
    for (const viewport of VIEWPORTS) {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      const control = page.locator('.maplibregl-ctrl-attrib');
      await expect(control).toHaveCount(1);
      await expect(control).not.toHaveClass(/maplibregl-compact-show/);
      await expect(control).not.toHaveAttribute('open');
      await expect(page.locator('.maplibregl-ctrl-attrib-inner')).toBeHidden();
      const button = await box(page, '.maplibregl-ctrl-attrib');
      expect(button.width).toBeLessThanOrEqual(32);
      expect(button.height).toBeLessThanOrEqual(32);
      expect(button.x + button.width).toBeGreaterThan(viewport.width - 40);
      expect(button.y + button.height).toBeGreaterThan(viewport.height - 40);

      await page.locator('.maplibregl-ctrl-attrib-button').click();
      await expect(page.locator('.maplibregl-ctrl-attrib-inner')).toBeVisible();
      await expect(page.locator('.maplibregl-ctrl-attrib-inner')).toContainText('OpenStreetMap');
      await context.close();
    }
  });

  test('requests nothing from outside the site below zoom 7, and street tiles from zoom 7', async ({
    browser,
    baseURL,
  }) => {
    const origin = new URL(baseURL ?? '').origin;
    // Once the service worker takes the page it fetches tiles itself, out of the route's sight.
    const context = await newContext(browser, DESKTOP, { serviceWorkers: 'block' });
    const page = await context.newPage();
    const external: string[] = [];
    await page.route(
      (url) => url.origin !== origin && url.protocol !== 'data:',
      async (route) => {
        external.push(route.request().url());
        await route.abort();
      },
    );
    await page.goto('/');
    await waitForTakeover(page);
    const canvas = page.locator('.maplibregl-canvas');
    await canvas.focus();

    // The initial view is zoom 4 at 1440x900. Each "=" zooms in by one level.
    const zoomIn = async (): Promise<void> => {
      await page.keyboard.press('Equal');
      await page.waitForTimeout(700);
    };
    await zoomIn();
    await zoomIn();
    expect(external).toEqual([]);
    await zoomIn();
    await expect.poll(() => external.length, { timeout: 10_000 }).toBeGreaterThan(0);
    expect(external.every((url) => url.startsWith('https://tiles.openfreemap.org/'))).toBe(true);
    await context.close();
  });
});

test.describe('build outputs', () => {
  test('the bundled geometry is current and within budget', () => {
    execFileSync(process.execPath, ['scripts/build-geo.mjs', '--check'], { cwd: WEB });
    const files = readdirSync(`${WEB}public/geo`).filter((name) => name.endsWith('.json'));
    expect(files).toHaveLength(1);
    const gzipped = files.reduce(
      (sum, name) => sum + gzipSync(readFileSync(`${WEB}public/geo/${name}`), { level: 9 }).length,
      0,
    );
    expect(gzipped).toBe(US_LINES_GZIP_BYTES);
    expect(gzipped).toBeLessThanOrEqual(60 * 1024);
  });

  test('the still and the WebGL map fit the same Web Mercator bounds', () => {
    // Recomputed here from the bounds MapLibre is given, with MapLibre's own projection.
    const x = (lng: number): number => (180 + lng) / 360;
    const y = (lat: number): number =>
      (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))) / 360;
    const [west, south, east, north] = US_BOUNDS;
    const aspect = (y(south) - y(north)) / (x(east) - x(west));
    const [, , width = NaN, height = NaN] = STILL_VIEWBOX.split(' ').map(Number);
    expect(height / width).toBeCloseTo(aspect, 5);

    const html = readFileSync(`${WEB}index.html`, 'utf8');
    expect(html).toContain(`viewBox="${STILL_VIEWBOX}"`);
    expect(html).toContain('preserveAspectRatio="xMidYMid meet"');
    // A phone's still covers its frame at the same proportions (limits.ts covers it alike).
    const [, , stillWidth = '', stillHeight = ''] = STILL_VIEWBOX.split(' ');
    expect(html).toContain(`height: max(100cqh, 100cqw * ${stillHeight} / ${stillWidth});`);
    expect(html).toContain(`aspect-ratio: ${stillWidth} / ${stillHeight};`);
  });

  test('the inline design tokens match src/styles/global.css', () => {
    const tokens = (css: string): Map<string, string> =>
      new Map(
        [...css.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((match) => [
          match[1] ?? '',
          (match[2] ?? '').trim().toLowerCase(),
        ]),
      );
    const inline = tokens(readFileSync(`${WEB}index.html`, 'utf8'));
    const global = tokens(readFileSync(`${WEB}src/styles/global.css`, 'utf8'));
    expect(global.size).toBeGreaterThan(0);
    for (const [name, value] of global) expect(inline.get(name), name).toBe(value);
  });
});

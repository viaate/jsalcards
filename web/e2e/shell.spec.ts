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

import { copy } from '../src/copy';
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
 * worker's source, and the bundled US lines.
 */
const MAP_DOWNLOADS = [
  'basemap',
  'maplibre',
  'maplibre-shared',
  'maplibre-worker',
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
  options: { javaScriptEnabled?: boolean } = {},
): Promise<BrowserContext> {
  return browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.deviceScaleFactor,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    javaScriptEnabled: options.javaScriptEnabled ?? true,
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

      // The still fills the frame, and the US lines fill the still on its limiting axis.
      const frame = await box(page, '.frame');
      const still = await box(page, 'svg.still');
      expect(still).toEqual(frame);
      const shot = await gray(await page.screenshot());
      const region = deviceRect(frame, viewport.deviceScaleFactor, shot, 2);
      const lit = litBounds(shot, viewport.deviceScaleFactor, region);
      const slackX = frame.width - lit.width;
      const slackY = frame.height - lit.height;
      expect(Math.min(slackX, slackY)).toBeLessThanOrEqual(3);
      expect(Math.abs(lit.x - frame.x - slackX / 2)).toBeLessThanOrEqual(2);
      expect(Math.abs(lit.y - frame.y - slackY / 2)).toBeLessThanOrEqual(2);

      // Sensible padding: clear of the search pill, off the screen edges.
      const bar = await box(page, '.bar');
      expect(lit.y).toBeGreaterThanOrEqual(bar.y + bar.height + 12);
      expect(lit.x).toBeGreaterThanOrEqual(12);
      expect(viewport.width - (lit.x + lit.width)).toBeGreaterThanOrEqual(12);
      expect(viewport.height - (lit.y + lit.height)).toBeGreaterThanOrEqual(16);
      // And the US is as large as that padding allows: most of the width.
      expect(lit.width / viewport.width).toBeGreaterThan(viewport.isMobile ? 0.85 : 0.75);

      // Nothing shown is data: no counts, times or statuses before anything has loaded.
      const text = await page.evaluate(() => document.body.innerText);
      expect(text).not.toMatch(/\d/);
      for (const status of Object.values(copy.status)) expect(text).not.toContain(status);

      expect(problems).toEqual([]);
      expect(foreign).toEqual([]);
      await context.close();
    });
  }

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
    expect(entryJs.length).toBeLessThan(60_000);
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
        .filter((entry) => /\/(assets|geo)\/(basemap|maplibre|us-lines)/.test(entry.name))
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
    const context = await newContext(browser, DESKTOP);
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

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
import {
  STILL_VIEWBOX,
  US_BOUNDS,
  US_LINES_FILE,
  US_NAMES_FILE,
  US_LINES_GZIP_BYTES,
  US_STATES_FILE,
} from '../src/map/basemap/us-geo';

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
/** A tablet held upright: wider than a phone, it opens on the country with its largest cities named. */
const TABLET: Viewport = {
  name: 'tablet 820x1180',
  width: 820,
  height: 1180,
  deviceScaleFactor: 2,
  isMobile: true,
};

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
  'us-names',
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

/**
 * The state names MapLibre placed (a phone's map names the states): the
 * bundled ones and the states in view closer in (state-areas.ts).
 */
async function stateNames(page: Page): Promise<string[]> {
  return page.evaluate(
    (layers) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const drawn = layers.filter((id) => map.getLayer(id) !== undefined);
      return map.queryRenderedFeatures({ layers: drawn }).flatMap((feature) => {
        const name: unknown = (feature.properties as Record<string, unknown>).name;
        return typeof name === 'string' ? [name] : [];
      });
    },
    [BASEMAP_IDS.usStateLabel, BASEMAP_IDS.usStateAreaLabel],
  );
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
  skip: readonly [number, number, number, number][] = [],
): Box {
  const [x0, y0, x1, y1] = region;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const skipped = (x: number, y: number): boolean =>
    skip.some(([sx0, sy0, sx1, sy1]) => x >= sx0 && x < sx1 && y >= sy0 && y < sy1);
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      if ((image.data[y * image.width + x] ?? 0) > threshold && !skipped(x, y)) {
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

/** Kansas City, Missouri: where the phone is in these tests, when it says. */
const KANSAS_CITY = { lat: 39.0997, lon: -94.5786 };

/** Cape Flattery, West Quoddy Head, Key West and the Northwest Angle: the country's ends. */
const COAST_POINTS: readonly (readonly [number, number])[] = [
  [-124.7, 48.38],
  [-66.98, 44.81],
  [-81.78, 24.56],
  [-95.15, 49.35],
];

/** Counts every read of the phone's position a page makes, from the start. */
async function countPositionReads(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    const counted = window as unknown as { positionReads: number };
    counted.positionReads = 0;
    const { geolocation } = navigator;
    const get = geolocation.getCurrentPosition.bind(geolocation);
    const follow = geolocation.watchPosition.bind(geolocation);
    geolocation.getCurrentPosition = (...args) => {
      counted.positionReads++;
      get(...args);
    };
    geolocation.watchPosition = (...args) => {
      counted.positionReads++;
      return follow(...args);
    };
  });
}

async function positionReads(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { positionReads: number }).positionReads);
}

/** The viewer lets the site know where they are: at `place`. */
async function allowPosition(
  context: BrowserContext,
  place: { lat: number; lon: number },
): Promise<void> {
  await context.grantPermissions(['geolocation']);
  await context.setGeolocation({ latitude: place.lat, longitude: place.lon });
}

/** The map's zoom and center, and where `place` is on the screen. */
async function mapState(
  page: Page,
  place: { lat: number; lon: number },
): Promise<{ zoom: number; center: { lat: number; lon: number }; x: number; y: number }> {
  return page.evaluate(({ lat, lon }) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    const point = map.project([lon, lat]);
    return {
      zoom: map.getZoom(),
      center: { lat: center.lat, lon: center.lng },
      x: point.x,
      y: point.y,
    };
  }, place);
}

/** What the page records of each animation frame from its start (recordHandover). */
interface HandoverSample {
  /** The still's opacity, or null once it has gone. */
  still: number | null;
  /** Whether the map's canvas is shown. */
  live: boolean;
}

interface HandoverWindow {
  handoverSamples: HandoverSample[];
  /** True once a dozen frames have gone by with the map shown and no still. */
  handoverDone: boolean;
}

/** Records, at every animation frame from the start of each page, whether the still and the map show. */
async function recordHandover(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    const record = window as unknown as HandoverWindow;
    record.handoverSamples = [];
    record.handoverDone = false;
    let after = 0;
    const tick = (): void => {
      const still = document.querySelector('svg.still');
      const live = document.querySelector('.maplibregl-map.is-live') !== null;
      record.handoverSamples.push({
        still: still === null ? null : Number(getComputedStyle(still).opacity),
        live,
      });
      if (live && still === null) after++;
      if (after >= 12) record.handoverDone = true;
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/** Records every frame the page paints, at CSS pixel size, until stop(). */
async function startScreencast(
  page: Page,
  viewport: Viewport,
): Promise<{ stop: () => Promise<Buffer[]> }> {
  const cdp = await page.context().newCDPSession(page);
  const shots: Buffer[] = [];
  cdp.on('Page.screencastFrame', (frame) => {
    shots.push(Buffer.from(frame.data, 'base64'));
    void cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => undefined);
  });
  await cdp.send('Page.startScreencast', {
    format: 'png',
    maxWidth: viewport.width,
    maxHeight: viewport.height,
    everyNthFrame: 1,
  });
  return {
    stop: async () => {
      await cdp.send('Page.stopScreencast');
      await cdp.detach();
      return shots;
    },
  };
}

/** A screencast frame in gray, at the viewport's CSS pixel size. */
async function grayAt(png: Buffer, viewport: Viewport): Promise<Gray> {
  return gray(
    await sharp(png).resize(viewport.width, viewport.height, { fit: 'fill' }).png().toBuffer(),
  );
}

/**
 * How much of the still a frame shows, and how much of anything else: the
 * share of the still's line pixels that are lit in the frame (within a
 * pixel), and the share of the pixels well away from any of the still's
 * lines that are lit (streets, water, names). The still alone is all outline
 * and no streets; the map at a street view, little outline and streets.
 */
function handoverLook(
  frame: Gray,
  still: Gray,
  region: [number, number, number, number],
  skip: readonly [number, number, number, number][],
): { outline: number; streets: number } {
  const [x0, y0, x1, y1] = region;
  const at = (image: Gray, x: number, y: number): number => image.data[y * image.width + x] ?? 0;
  const brightest = (image: Gray, x: number, y: number, reach: number): number => {
    let most = 0;
    for (let dy = -reach; dy <= reach; dy++) {
      for (let dx = -reach; dx <= reach; dx++) most = Math.max(most, at(image, x + dx, y + dy));
    }
    return most;
  };
  const skipped = (x: number, y: number): boolean =>
    skip.some(([sx0, sy0, sx1, sy1]) => x >= sx0 && x < sx1 && y >= sy0 && y < sy1);
  let lines = 0;
  let linesLit = 0;
  let away = 0;
  let awayLit = 0;
  for (let y = y0 + 3; y < y1 - 3; y++) {
    for (let x = x0 + 3; x < x1 - 3; x++) {
      if (skipped(x, y)) continue;
      if (at(still, x, y) > 40) {
        lines++;
        if (brightest(frame, x, y, 1) > 20) linesLit++;
      } else if (brightest(still, x, y, 3) < 8) {
        away++;
        if (at(frame, x, y) > 24) awayLit++;
      }
    }
  }
  const round = (value: number): number => Math.round(value * 10_000) / 10_000;
  return {
    outline: round(lines === 0 ? 0 : linesLit / lines),
    streets: round(away === 0 ? 0 : awayLit / away),
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
      // The still fills the frame, and the US lines fill the still on its limiting axis: the
      // whole country, nothing cropped, on a phone too.
      expect(still).toEqual(frame);
      const region = deviceRect(frame, viewport.deviceScaleFactor, shot, 2);
      // The key's chip and a phone's button sit at the frame's foot: they are not the map.
      const controls = await Promise.all(
        ['ul.legend', 'button.locate']
          .filter((selector) => selector === 'ul.legend' || viewport.isMobile)
          .map(async (selector) =>
            deviceRect(await box(page, selector), viewport.deviceScaleFactor, shot, 2),
          ),
      );
      const lit = litBounds(shot, viewport.deviceScaleFactor, region, 24, controls);
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
      if (viewport.isMobile) {
        // A phone held upright: the country from one side of the page to the other, as wide as
        // the search field, and centered down between the field and the key.
        const field = await box(page, '.search');
        const legend = await box(page, 'ul.legend');
        expect(Math.abs(lit.x - field.x)).toBeLessThanOrEqual(2);
        expect(Math.abs(lit.x + lit.width - (field.x + field.width))).toBeLessThanOrEqual(2);
        const middle = (field.y + field.height + legend.y) / 2;
        expect(Math.abs(lit.y + lit.height / 2 - middle)).toBeLessThanOrEqual(3);
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

      // The menu's button across from the wordmark, on its line at the right edge, clear of the field.
      const menu = await box(page, 'button.menu-button');
      await expect(page.locator('button.menu-button')).toHaveAttribute(
        'aria-label',
        copy.menu.label,
      );
      expect(menu.width, where).toBe(36);
      expect(menu.height, where).toBe(36);
      expect(viewport.width - (menu.x + menu.width), where).toBe(16);
      expect(Math.abs(menu.y + menu.height / 2 - (name.y + name.height / 2)), where).toBeLessThan(
        1,
      );
      expect(menu.y + menu.height, where).toBeLessThanOrEqual(field.y - 4);

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

      // The country between the field and the key: the frame starts as far under the field as
      // it ends over the key, as wide as the field, and the still fills it, the whole country.
      const frame = await box(page, '.frame');
      const still = await box(page, 'svg.still');
      const above = frame.y - (field.y + field.height);
      const below = legend.y - (frame.y + frame.height);
      expect(above, where).toBe(24);
      // The narrowest phones' key takes two lines, and part of the gap under the frame.
      expect(below, where).toBeGreaterThanOrEqual(viewport.width >= 375 ? 24 : 0);
      expect(still, where).toEqual(frame);
      expect(frame.x, where).toBe(field.x);
      expect(frame.width, where).toBe(field.width);

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

  test('lays a wider screen out with the field just after the name, in either face', async ({
    browser,
  }) => {
    // The owner's call: from 720px wide, the field at the left, after the wordmark.
    const screens: Viewport[] = [
      { ...DESKTOP, name: 'narrow window 720x900', width: 720 },
      { ...DESKTOP, name: 'window 1024x768', width: 1024, height: 768 },
      DESKTOP,
      { ...DESKTOP, name: 'wide 2560x1440', width: 2560, height: 1440 },
      { ...PHONE, name: 'phone held sideways 844x390', width: 844, height: 390 },
    ];
    for (const viewport of screens) {
      for (const face of ['Geist', 'fallback'] as const) {
        const where = `${viewport.name}, ${face}`;
        const context = await newContext(browser, viewport);
        const page = await context.newPage();
        if (face === 'fallback') await page.route(/\.woff2$/, (route) => route.abort());
        await page.goto('/', { waitUntil: 'load' });
        if (face === 'Geist') {
          await expect
            .poll(() => page.evaluate(() => document.fonts.check('600 17px "Geist Variable"')))
            .toBe(true);
        }

        // The field starts where the name's slot and the gap after it end, whatever the face
        // (so a font swap never moves it), and narrows before the 180px kept at the right for
        // the update time does, as it does for the menu's button after it (10px on, 44px wide,
        // 12px clear of the time). The name sits clear of it, on its line.
        const name = await box(page, 'h1.wordmark');
        const field = await box(page, '.search');
        expect(name.x, where).toBe(20);
        expect(field.x, where).toBe(20 + 84 + 20);
        expect(field.width, where).toBe(
          Math.min(400, viewport.width - 40 - 84 - 20 - (10 + 44 + 12) - 180),
        );
        expect(name.x + name.width, where).toBeLessThanOrEqual(field.x - 8);
        expect(
          Math.abs(name.y + name.height / 2 - (field.y + field.height / 2)),
          where,
        ).toBeLessThan(1);
        // The menu's button just after the field, as tall as it and level with it.
        const menu = await box(page, 'button.menu-button');
        expect(menu.x, where).toBe(field.x + field.width + 10);
        expect([menu.y, menu.width, menu.height], where).toEqual([
          field.y,
          field.height,
          field.height,
        ]);
        await context.close();
      }
    }
  });

  test('the key keeps its place as the font loads, on every screen', async ({ browser }) => {
    test.setTimeout(180_000);
    const SMALL: Viewport = { ...PHONE, name: 'phone 360x740', width: 360, height: 740 };
    const NARROWEST: Viewport = { ...PHONE, name: 'phone 320x568', width: 320, height: 568 };
    const WIDE_PHONE: Viewport = { ...PHONE, name: 'phone 412x839', width: 412, height: 839 };
    for (const viewport of [DESKTOP, WIDE_PHONE, PHONE, SMALL, NARROWEST]) {
      for (const delay of [300, 1500]) {
        const context = await newContext(browser, viewport);
        const page = await context.newPage();
        await page.addInitScript(() => {
          const shifts: string[] = [];
          (window as unknown as { __shifts: string[] }).__shifts = shifts;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              const { value, sources } = entry as unknown as {
                value: number;
                sources: { node?: Node | null }[];
              };
              shifts.push(
                `${String(value)} ${sources.map((source) => source.node?.textContent?.trim() ?? '?').join(' | ')}`,
              );
            }
          }).observe({ type: 'layout-shift', buffered: true });
        });
        await page.route(/\.woff2$/, async (route) => {
          await new Promise((resolve) => setTimeout(resolve, delay));
          await route.continue().catch(() => undefined);
        });
        await page.goto('/');
        await page.waitForFunction(() => document.fonts.check('450 12px "Geist Variable"'), null, {
          timeout: delay + 10_000,
        });
        await page.waitForTimeout(500);
        const label = `${viewport.name}, font after ${String(delay)} ms`;
        expect(
          await page.evaluate(() => (window as unknown as { __shifts: string[] }).__shifts),
          label,
        ).toEqual([]);
        // Set in Geist, every word fits the slot its key keeps.
        const overflow = await page.evaluate(() =>
          [...document.querySelectorAll('ul.legend li')].map((item) => {
            const range = document.createRange();
            range.selectNodeContents(item);
            return range.getBoundingClientRect().right - item.getBoundingClientRect().right;
          }),
        );
        for (const past of overflow)
          expect(past, `${label}: ${overflow.join(', ')}`).toBeLessThanOrEqual(0.5);
        await context.close();
      }
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
      // The map names the largest cities on a desktop once its first frame is up; a phone's
      // whole country is too small for names. The still carries none.
      await whenIdle(page);
      const named = await cityNames(page);
      if (viewport.isMobile) expect(named).toEqual([]);
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

  for (const opening of [
    { name: 'its viewer’s own area, where they have let the site know', path: '/', near: true },
    { name: 'a shared link', path: '/?at=40.7128,-74.006,12', near: false },
  ]) {
    test(`a phone opening on ${opening.name} never lays the country over the streets: every frame of the handover`, async ({
      browser,
    }) => {
      test.setTimeout(120_000);
      // Reference: the still alone, as painted with no script at all.
      const staticContext = await newContext(browser, PHONE, { javaScriptEnabled: false });
      const staticPage = await staticContext.newPage();
      await staticPage.goto('/', { waitUntil: 'load' });
      const reference = await gray(await staticPage.screenshot({ scale: 'css' }));
      await staticContext.close();

      const context = await newContext(browser, PHONE);
      if (opening.near) await allowPosition(context, KANSAS_CITY);
      await recordHandover(context);
      const page = await context.newPage();
      const screencast = await startScreencast(page, PHONE);
      await page.goto(opening.path);
      await waitForTakeover(page);
      await whenIdle(page);
      // A few frames of the map on its own after the still has gone.
      await page.waitForFunction(() => (window as unknown as HandoverWindow).handoverDone, null, {
        timeout: 30_000,
      });
      const shots = await screencast.stop();
      const view = await mapState(page, KANSAS_CITY);
      expect(view.zoom, 'opens at a street view').toBeGreaterThanOrEqual(10);

      // Every animation frame: the still (the whole country) or the map, never both, never neither.
      const samples = await page.evaluate(
        () => (window as unknown as HandoverWindow).handoverSamples,
      );
      const first = samples.findIndex((sample) => sample.still !== null);
      expect(first, 'the still is up from the first frame').toBeGreaterThanOrEqual(0);
      const since = samples.slice(first);
      const both = since.filter((sample) => sample.live && sample.still !== null);
      const neither = since.filter((sample) => !sample.live && sample.still === null);
      const fading = since.filter((sample) => sample.still !== null && sample.still < 1);
      test.info().annotations.push({
        type: 'handover frames',
        description: `${String(since.length)} frames, still until ${String(
          since.findIndex((sample) => sample.still === null),
        )}`,
      });
      expect(both, 'frames with the country over the map').toEqual([]);
      expect(neither, 'frames with neither the still nor the map').toEqual([]);
      expect(fading, 'the still goes at once, it does not fade over the streets').toEqual([]);
      expect(since.some((sample) => sample.live)).toBe(true);

      // And in pixels, as the screen showed them: each frame is the country's outline on black,
      // or the streets, never the outline stamped over streets, and no frame between is empty.
      const frame = await box(page, '.frame');
      const region = deviceRect(frame, 1, reference);
      const skip = [
        deviceRect(await box(page, 'button.locate'), 1, reference, 2),
        deviceRect(await box(page, '.maplibregl-ctrl-attrib'), 1, reference, 2),
      ];
      const looks = [];
      for (const shot of shots) {
        looks.push(handoverLook(await grayAt(shot, PHONE), reference, region, skip));
      }
      test.info().annotations.push({
        type: 'handover pixels',
        description: JSON.stringify(looks),
      });
      // From the first frame of the still alone (the first frames are the blank page before it).
      const firstStill = looks.findIndex((look) => look.outline > 0.9 && look.streets < 0.002);
      expect(firstStill, 'a frame of the still alone').toBeGreaterThanOrEqual(0);
      const shown = looks.slice(firstStill);
      expect(
        shown.filter((look) => look.outline > 0.8 && look.streets > 0.005),
        'frames with the country laid over the streets',
      ).toEqual([]);
      expect(
        shown.filter((look) => look.outline <= 0.8 && look.streets <= 0.005),
        'empty frames between the still and the map',
      ).toEqual([]);
      expect(
        shown.some((look) => look.outline < 0.6 && look.streets > 0.02),
        'a frame of the streets alone',
      ).toBe(true);
      await context.close();
    });
  }

  test('loads MapLibre after first paint, through a dynamic import', async ({
    browser,
    request,
  }) => {
    const html = await (await request.get('/')).text();
    // The page names no map code: MapLibre's class names are in its styles, never a script of it.
    expect(html).not.toMatch(/basemap-|maplibre[\w-]*\.(?:js|css)|<link[^>]+stylesheet/);
    expect(html).toMatch(/\.maplibregl-map\s*\{/);
    const entry = /<script type="module" crossorigin src="([^"]+)"/.exec(html)?.[1];
    expect(entry).toBeDefined();
    const entryJs = await (await request.get(entry ?? '')).text();
    // MapLibre alone is about 800 kB. The entry is the shell, Svelte and the copy module,
    // whose formatters (the update time's among them) come with it wherever they are used. The
    // menu's button is in it; the menu itself, and what it reads, load with the first press.
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
          /\/(assets|geo)\/(basemap|maplibre|street-tiles|us-lines|us-names)/.test(entry.name),
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

    // Each of the map's scripts once (the rest of its downloads are the bundled lines' files).
    expect(map.map((script) => script.name).sort()).toEqual(
      MAP_DOWNLOADS.filter((name) => !name.startsWith('us-')).sort(),
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

  test('sets the city names off the coasts and borders, a halo and more from any of them', async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    // The names a coast or border runs by (the ones the judges saw on a line, and their like),
    // wherever a screen names them at its home view.
    const BY_A_LINE = [
      'Seattle',
      'Portland',
      'San Francisco',
      'Los Angeles',
      'El Paso',
      'Houston',
      'Miami',
      'Tampa',
      'New York',
      'Boston',
      'Washington',
      'Detroit',
      'Chicago',
    ];
    const onLine: string[] = [];
    // The screen the names were set off the lines for: a phone's whole country, small, names none.
    for (const [viewport, zone, fewest] of [[DESKTOP, 'UTC', 10]] as const) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: viewport.deviceScaleFactor,
        isMobile: viewport.isMobile,
        hasTouch: viewport.isMobile,
        timezoneId: zone,
      });
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      await whenIdle(page);
      const named = await cityNames(page);
      const checked = BY_A_LINE.filter((city) => named.includes(city));
      expect(checked.length, `${viewport.name}, ${zone}`).toBeGreaterThanOrEqual(fewest);

      /**
       * Draws only the outline (the coast and the border), or only one city's name, or
       * neither, over the ground, and waits for the frame.
       */
      const drawOnly = async (outline: boolean, city: string | null): Promise<Gray> => {
        await page.evaluate(
          ({ outline: showOutline, city: name, prefix, outlineIds }) =>
            new Promise<void>((resolve) => {
              const map = window.snowlightMap;
              if (map === undefined) throw new Error('no map');
              const saved = window as unknown as { cityFilters?: Record<string, unknown> };
              saved.cityFilters ??= Object.fromEntries(
                map
                  .getStyle()
                  .layers.filter((layer) => layer.id.startsWith(prefix))
                  .map((layer) => [layer.id, map.getFilter(layer.id)]),
              );
              for (const layer of map.getStyle().layers) {
                if (layer.type === 'background') continue;
                const own = saved.cityFilters[layer.id];
                if (own !== undefined) {
                  map.setLayoutProperty(layer.id, 'visibility', name === null ? 'none' : 'visible');
                  if (name !== null) {
                    map.setFilter(layer.id, [
                      'all',
                      own as never,
                      ['==', ['get', 'name'], name],
                    ] as never);
                  }
                } else {
                  const shown = showOutline && outlineIds.includes(layer.id);
                  map.setLayoutProperty(layer.id, 'visibility', shown ? 'visible' : 'none');
                }
              }
              map.once('idle', () => {
                // Past the names' fade-in.
                setTimeout(() => {
                  requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                      resolve();
                    });
                  });
                }, 400);
              });
              map.triggerRepaint();
            }),
          {
            outline,
            city,
            prefix: BASEMAP_IDS.usCityLabel,
            outlineIds: [BASEMAP_IDS.usOutlineSimple, BASEMAP_IDS.usOutline] as string[],
          },
        );
        return gray(await page.screenshot());
      };
      const ground = await drawOnly(false, null);
      const lines = await drawOnly(true, null);
      // Lit past the faint edge a line's or a letter's smoothing leaves.
      const lit = (shot: Gray, i: number): boolean =>
        Math.abs((shot.data[i] ?? 0) - (ground.data[i] ?? 0)) > 40;
      // Clear of a line by the name's halo and a pixel more, in device pixels.
      const apart = 2 * viewport.deviceScaleFactor;
      for (const city of checked) {
        const name = await drawOnly(false, city);
        const { width, height } = name;
        let glyphs = 0;
        let touching = 0;
        for (let y = 0; y < height; y++) {
          for (let x = 0; x < width; x++) {
            if (!lit(name, y * width + x)) continue;
            glyphs++;
            let near = false;
            for (let dy = -apart; dy <= apart && !near; dy++) {
              for (let dx = -apart; dx <= apart && !near; dx++) {
                const [nx, ny] = [x + dx, y + dy];
                if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
                near = lit(lines, ny * width + nx);
              }
            }
            if (near) touching++;
          }
        }
        expect(glyphs, `${viewport.name}, ${zone}: ${city} is drawn`).toBeGreaterThan(20);
        if (touching > 0) onLine.push(`${viewport.name}, ${zone}, ${city}: ${String(touching)} px`);
      }
      await context.close();
    }
    expect(onLine, 'names near the outline').toEqual([]);
  });

  test('a phone opens on the whole country, Washington to Maine, and asks no one where they are', async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const LANDSCAPE: Viewport = { ...PHONE, name: 'phone 844x390', width: 844, height: 390 };
    const SMALL: Viewport = { ...PHONE, name: 'phone 320x568', width: 320, height: 568 };
    for (const viewport of [PHONE, SMALL, LANDSCAPE, DESKTOP]) {
      const where = viewport.name;
      const context = await newContext(browser, viewport);
      await countPositionReads(context);
      // A desktop opens on the national view even where its viewer has let the site know.
      if (viewport === DESKTOP) await allowPosition(context, KANSAS_CITY);
      const page = await context.newPage();
      await page.goto('/');
      await waitForTakeover(page);
      await whenIdle(page);
      expect(new URL(page.url()).search, where).toBe('');
      expect(await positionReads(page), where).toBe(0);
      // Both coasts whole on screen, and the Keys: nothing cropped.
      const points = await page.evaluate((places) => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        return places.map(([lon, lat]) => map.project([lon, lat]));
      }, COAST_POINTS);
      for (const [i, point] of points.entries()) {
        const at = `${where}: ${JSON.stringify(COAST_POINTS[i])}`;
        expect(point.x, at).toBeGreaterThan(8);
        expect(point.x, at).toBeLessThan(viewport.width - 8);
        expect(point.y, at).toBeGreaterThan(0);
        expect(point.y, at).toBeLessThan(viewport.height);
      }
      if (viewport === PHONE || viewport === SMALL) {
        // The country from one side of the page to the other: Cape Flattery and West Quoddy
        // Head at the search field's two ends.
        const field = await box(page, '.search');
        const { west, east } = await page.evaluate(
          ({ w, e }) => {
            const map = window.snowlightMap;
            if (map === undefined) throw new Error('no map');
            return { west: map.project([w, 48]).x, east: map.project([e, 45]).x };
          },
          { w: US_BOUNDS[0], e: US_BOUNDS[2] },
        );
        expect(Math.abs(west - field.x), where).toBeLessThan(2);
        expect(Math.abs(east - (field.x + field.width)), where).toBeLessThan(2);
      }
      await context.close();
    }
  });

  test('a phone its viewer has let the site know about opens over their own area', async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const context = await newContext(browser, PHONE);
    await countPositionReads(context);
    await allowPosition(context, KANSAS_CITY);
    const page = await context.newPage();
    await page.goto('/');
    await waitForTakeover(page);
    await whenIdle(page);
    // A metro's zoom, Kansas City in the middle of the map between the search field and the
    // key, and no view in the address: it is the home view.
    const view = await mapState(page, KANSAS_CITY);
    expect(view.zoom).toBeCloseTo(10, 5);
    const field = await box(page, '.search');
    const legend = await box(page, 'ul.legend');
    expect(Math.abs(view.x - PHONE.width / 2)).toBeLessThan(2);
    expect(Math.abs(view.y - (field.y + field.height + legend.y) / 2)).toBeLessThan(2);
    expect(new URL(page.url()).search).toBe('');
    expect(await positionReads(page)).toBe(1);
    await context.close();

    // Far from the continental US, it opens on the whole country.
    const abroad = await newContext(browser, PHONE);
    await allowPosition(abroad, { lat: 43.6532, lon: -79.3832 });
    const away = await abroad.newPage();
    await away.goto('/');
    await waitForTakeover(away);
    await whenIdle(away);
    expect((await mapState(away, KANSAS_CITY)).zoom).toBeLessThan(3);
    await abroad.close();
  });

  test('a shared link opens as sent, wherever the viewer is', async ({ browser }) => {
    test.setTimeout(120_000);
    for (const query of [
      '?at=40.7128,-74.006,12',
      '?school=A1902690',
      '?district=2900001',
      '?zip=64111',
    ]) {
      const context = await newContext(browser, PHONE);
      await countPositionReads(context);
      await allowPosition(context, KANSAS_CITY);
      const page = await context.newPage();
      await page.goto(`/${query}`);
      await waitForTakeover(page);
      await whenIdle(page);
      const view = await mapState(page, KANSAS_CITY);
      // Where the link says (this build ships no data to place a school, district or ZIP code
      // by: the map stays on the country), never the viewer's own area.
      if (query.startsWith('?at=')) {
        expect(view.zoom, query).toBeCloseTo(12, 5);
        expect(view.center.lat, query).toBeCloseTo(40.7128, 3);
      } else {
        expect(view.zoom, query).toBeLessThan(3);
      }
      expect(await positionReads(page), query).toBe(0);
      await context.close();
    }
  });

  test('“Show my area” asks when tapped, and from then on the phone opens there', async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const context = await newContext(browser, PHONE);
    await countPositionReads(context);
    const page = await context.newPage();
    await page.goto('/');
    await waitForTakeover(page);
    await whenIdle(page);
    expect((await mapState(page, KANSAS_CITY)).zoom).toBeLessThan(3);
    expect(await positionReads(page)).toBe(0);
    // The viewer taps the button and lets the site know.
    await allowPosition(context, KANSAS_CITY);
    await page.locator('button.locate').tap();
    await expect
      .poll(async () => (await mapState(page, KANSAS_CITY)).zoom, { timeout: 30_000 })
      .toBeCloseTo(10, 3);
    await whenIdle(page);
    const view = await mapState(page, KANSAS_CITY);
    expect(Math.abs(view.x - PHONE.width / 2)).toBeLessThan(2);
    // Its own area is the home view now: the address names no view.
    await expect.poll(() => new URL(page.url()).search).toBe('');
    // And the next visit opens there.
    await page.reload();
    await waitForTakeover(page);
    await whenIdle(page);
    expect((await mapState(page, KANSAS_CITY)).zoom).toBeCloseTo(10, 5);
    await context.close();
  });

  test('a phone names every state in view with room for its name, closer in; the whole country and a wider screen none', async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    // The whole country on a phone: too small for any state's name to read.
    const phone = await newContext(browser, PHONE);
    const page = await phone.newPage();
    await page.goto('/');
    await waitForTakeover(page);
    await whenIdle(page);
    expect(await stateNames(page)).toEqual([]);

    // The owner's old opening view, the middle of the country filling a phone's height: every
    // state there with room for its name is named, Kansas and Texas among them, each once.
    const VIEWS: [at: string, named: readonly string[]][] = [
      [
        '38.5,-95.8,3.85',
        [
          'Kansas',
          'Texas',
          'Illinois',
          'Wisconsin',
          'Arkansas',
          'Louisiana',
          'Missouri',
          'Iowa',
          'Nebraska',
          'Oklahoma',
          'Minnesota',
          'South Dakota',
          'North Dakota',
        ],
      ],
      // A region around Kansas City, where most states run off the screen.
      ['38.9,-95,5', ['Kansas', 'Missouri', 'Iowa', 'Nebraska', 'Oklahoma', 'Arkansas', 'Texas']],
      ['39,-94.8,6.5', ['Kansas', 'Missouri']],
      // The metro, on the state line: both states, from the street tiles' zoom on too.
      ['39.1,-94.58,10', ['Kansas', 'Missouri']],
    ];
    for (const [at, named] of VIEWS) {
      await page.goto(`/?at=${at}`);
      await waitForTakeover(page);
      await whenIdle(page);
      await expect
        .poll(async () => stateNames(page), { timeout: 30_000, message: at })
        .toEqual(expect.arrayContaining([...named]));
      const states = await stateNames(page);
      test.info().annotations.push({ type: at, description: states.join(', ') });
      expect(new Set(states).size, at).toBe(states.length);
      // Each whole on the screen, in the frame between the search field and the key.
      const boxes = await page.evaluate(
        (layers) => {
          const map = window.snowlightMap;
          if (map === undefined) throw new Error('no map');
          const canvas = map.getCanvas();
          const { width, height } = canvas.getBoundingClientRect();
          const drawn = layers.filter((id) => map.getLayer(id) !== undefined);
          const cut: string[] = [];
          for (const [name, box] of [
            ['left', [0, 0, 1, height]],
            ['right', [width - 1, 0, width, height]],
            ['top', [0, 0, width, 1]],
            ['bottom', [0, height - 1, width, height]],
          ] as const) {
            for (const feature of map.queryRenderedFeatures(
              [
                [box[0], box[1]],
                [box[2], box[3]],
              ],
              { layers: drawn },
            )) {
              cut.push(`${String(feature.properties.name)} at the ${name} edge`);
            }
          }
          return cut;
        },
        [BASEMAP_IDS.usStateLabel, BASEMAP_IDS.usStateAreaLabel],
      );
      expect(boxes, at).toEqual([]);
    }
    await phone.close();

    // A wider screen names no state, at its national view or closer in.
    const desktop = await newContext(browser, DESKTOP);
    const wide = await desktop.newPage();
    for (const path of ['/', '/?at=38.9,-95,5']) {
      await wide.goto(path);
      await waitForTakeover(wide);
      await whenIdle(wide);
      expect(await stateNames(wide), path).toEqual([]);
    }
    await desktop.close();
  });

  test('a phone never names a state twice, at rest or on the way', async ({ browser }) => {
    test.setTimeout(240_000);
    const context = await newContext(browser, PHONE);
    // Every frame the page draws, the states named more than once (by either layer, or both).
    await context.addInitScript(
      (layers) => {
        const seen: string[] = [];
        (window as unknown as { stateTwice: string[] }).stateTwice = seen;
        const look = (): void => {
          const map = window.snowlightMap;
          if (map?.getLayer(layers[0] ?? '') !== undefined) {
            const drawn = layers.filter((id) => map.getLayer(id) !== undefined);
            const count = new Map<string, number>();
            for (const feature of map.queryRenderedFeatures({ layers: drawn })) {
              const name = String(feature.properties.name);
              count.set(name, (count.get(name) ?? 0) + 1);
            }
            for (const [name, times] of count) if (times > 1) seen.push(name);
          }
          requestAnimationFrame(look);
        };
        requestAnimationFrame(look);
      },
      [BASEMAP_IDS.usStateLabel, BASEMAP_IDS.usStateAreaLabel],
    );
    const page = await context.newPage();
    const twice = (): Promise<string[]> =>
      page.evaluate(() => [...new Set((window as unknown as { stateTwice: string[] }).stateTwice)]);
    // Where a judge saw Iowa named twice, by both layers: its bundled name under the search field.
    await page.goto('/?at=37.5,-96,5');
    await waitForTakeover(page);
    await whenIdle(page);
    await expect
      .poll(async () => stateNames(page), { timeout: 30_000 })
      .toEqual(expect.arrayContaining(['Kansas', 'Missouri', 'Oklahoma', 'Nebraska', 'Texas']));
    expect(await twice()).toEqual([]);
    // Views across the country from the bundled names' first zoom to the street tiles', each
    // eased to as a hand would, every frame on the way and at rest looked at.
    for (const zoom of [3.4, 4.5, 5.5, 6.5]) {
      for (const [lat, lon] of [
        [31, -100],
        [38, -112],
        [42, -93],
        [36, -80],
        [44, -72],
      ] as const) {
        await page.evaluate(
          ([center, to]) =>
            new Promise<void>((resolve) => {
              const map = window.snowlightMap;
              if (map === undefined) throw new Error('no map');
              map.once('moveend', () => {
                resolve();
              });
              map.easeTo({ center, zoom: to, duration: 300 });
            }),
          [[lon, lat] as [number, number], zoom] as const,
        );
        await whenIdle(page);
        // The names the map sets as it comes to rest, and the frames that follow.
        await page.waitForTimeout(600);
        const at = `${String(lat)},${String(lon)},${String(zoom)}`;
        const states = await stateNames(page);
        test.info().annotations.push({ type: at, description: states.join(', ') });
        expect(new Set(states).size, at).toBe(states.length);
        expect(await twice(), at).toEqual([]);
      }
    }
    await context.close();
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
    // The lines the map opens with, their names alone (what the page reads of them), and the
    // states' shapes a phone names the states in view by.
    expect(files.map((name) => `geo/${name}`).sort()).toEqual(
      [US_LINES_FILE, US_NAMES_FILE, US_STATES_FILE].sort(),
    );
    const features = (file: string): unknown[] =>
      (JSON.parse(readFileSync(`${WEB}public/${file}`, 'utf8')) as { features: unknown[] })
        .features;
    const kind = (feature: unknown): unknown =>
      (feature as { properties: { kind: unknown } }).properties.kind;
    expect(features(US_NAMES_FILE)).toEqual(
      features(US_LINES_FILE).filter((feature) =>
        ['city', 'state-name'].includes(String(kind(feature))),
      ),
    );
    const gzipped = (file: string): number =>
      gzipSync(readFileSync(`${WEB}public/${file}`), { level: 9 }).length;
    expect(gzipped(US_LINES_FILE)).toBe(US_LINES_GZIP_BYTES);
    expect(gzipped(US_LINES_FILE)).toBeLessThanOrEqual(60 * 1024);
    expect(gzipped(US_STATES_FILE)).toBeLessThanOrEqual(48 * 1024);
    expect(gzipped(US_NAMES_FILE)).toBeLessThanOrEqual(12 * 1024);
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
    // On every screen, a phone's too: the still is never laid out another way.
    expect(html).not.toMatch(/\.still\s*\{[^}]*(?:translate|aspect-ratio|cqh)/);
    expect(html).not.toContain('--home-fit');
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

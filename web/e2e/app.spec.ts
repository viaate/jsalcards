/**
 * The integrated app: the shell, the map with its glow, search, share links,
 * the pinned school and the service worker, working as one.
 *
 * Two builds are checked:
 *
 * - the default build (playwright.config.ts builds it), which ships no data:
 *   nothing under data/ is ever requested, nothing glows, search shows
 *   nothing, and the build holds no data of any kind;
 * - a build with data staged in its public/data/ folder, made here in a
 *   temporary folder. Its search index is built by scripts/build-search-index.mjs
 *   from real records: two cities and one ZIP code copied from the pipeline's
 *   search records, and two schools with the names and places the pipeline's
 *   school directory gives them. Its directory holds those two schools as the
 *   pipeline wrote them. Its closings file is SYNTHETIC: no real closings exist
 *   in September, so the two statuses are made up for this test and live only
 *   in the temporary folder while it runs.
 *
 * Runs once, under the desktop project; tests set their own viewports.
 * WebGL here is SwiftShader, whose frames are slow, and a page's first flight
 * into streets holds the page for seconds (FIRST_FLIGHT_MS). A test that
 * waits on the map or on a timer waits in real time, with the date fixed
 * alone (fixDate): a faked clock would stretch each by the frames it draws.
 */
import { execFileSync } from 'node:child_process';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { devices, expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { STATUS_KEYS, copy, format } from '../src/copy';
import { COPIED_MS } from '../src/ui/share';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const FIRST_LABEL_LAYER = 'ofm-label-neighbourhood';
const PEMBROKE_HILL = 'A1902690';
const BORDER_STAR = { lon: -94.592692, lat: 39.013304 };
/** Where the school panel beside the map ends: its gap from the screen's edge and its width (app/frame.ts). */
const PANEL_RIGHT = 20 + 368;
/** Where Pembroke Hill is, as the directory has it. */
const PEMBROKE_HILL_PLACE = { lon: -94.593001, lat: 39.03606 };
const PIN_KEY = 'snowlight:pin';
/** Chrome's own lines about SwiftShader, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

/** Words that would give away made-up data in a build. */
const SYNTHETIC_MARKERS = /synthetic|lorem ipsum|sample data|placeholder data|dummy data|fixture/i;

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

test.describe.configure({ timeout: 120_000 });

interface Watch {
  problems: string[];
  requests: string[];
}

/** Console errors and warnings, page errors, failed and non-2xx requests, and every URL asked for. */
function watch(page: Page): Watch {
  const problems: string[] = [];
  const requests: string[] = [];
  page.on('console', (message) => {
    const type = message.type();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(message.text())) {
      problems.push(`console.${type}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    // The map cancels tiles it no longer needs, and leaving a page cancels what it was loading.
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
      problems.push(`requestfailed: ${request.url()}`);
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400)
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
  });
  page.on('request', (request) => requests.push(request.url()));
  return { problems, requests };
}

/**
 * Stops the page's calendar at `now`, and nothing else: `new Date()` and `Date.now()` give `now`,
 * while timers, animation frames and performance.now run as they do. page.clock fakes those too,
 * and its time then moves on 16 ms for each frame the page draws: where a frame takes longer, as
 * the map's do in software, a flight or a timer takes that many times as long in real time.
 */
async function fixDate(page: Page, now: Date): Promise<void> {
  await page.addInitScript((time: number) => {
    class FixedDate extends Date {
      constructor(...args: unknown[]) {
        super(...((args.length === 0 ? [time] : args) as [number]));
      }

      static override now(): number {
        return time;
      }
    }
    globalThis.Date = FixedDate as unknown as DateConstructor;
  }, now.getTime());
}

async function waitForMap(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 30_000,
  });
}

interface GlowStats {
  count: number;
  glowCount: number;
  frames: number;
  mode: string;
}

/** Every layout shift the page has had, by the text of what moved: none is ever expected. */
async function layoutShifts(page: Page): Promise<string[]> {
  return page.evaluate(
    () =>
      new Promise<string[]>((resolve) => {
        const done = (shifts: string[]): void => {
          observer.disconnect();
          resolve(shifts);
        };
        const observer = new PerformanceObserver((list) => {
          done(
            list.getEntries().map((entry) => {
              const { value, sources } = entry as unknown as {
                value: number;
                sources: { node?: Node | null }[];
              };
              const moved = sources.map((source) => source.node?.textContent?.trim() ?? '?');
              return `${String(value)} ${moved.join(' | ')}`;
            }),
          );
        });
        // Buffered: the shifts so far come at once, and with none nothing comes.
        observer.observe({ type: 'layout-shift', buffered: true });
        setTimeout(() => {
          done([]);
        }, 500);
      }),
  );
}

/** The glow layer's own numbers, once it is on the map. */
async function glowStats(page: Page): Promise<GlowStats> {
  await page.waitForFunction((id) => window.snowlightMap?.getLayer(id) !== undefined, GLOW_LAYER, {
    timeout: 30_000,
  });
  return page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as {
      implementation: { stats: GlowStats };
    };
    const { count, glowCount, frames, mode } = layer.implementation.stats;
    return { count, glowCount, frames, mode };
  }, GLOW_LAYER);
}

/** Resolves once the map is at rest with every tile in. */
async function settleMap(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout: 30_000, polling: 100 },
  );
}

/** Where a place is on the screen, in CSS pixels. */
async function onScreen(
  page: Page,
  place: { readonly lon: number; readonly lat: number },
): Promise<{ x: number; y: number }> {
  return page.evaluate(({ lon, lat }) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const point = map.project([lon, lat]);
    const box = map.getContainer().getBoundingClientRect();
    return { x: box.left + point.x, y: box.top + point.y };
  }, place);
}

async function mapView(page: Page): Promise<{ lat: number; lon: number; zoom: number }> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
  });
}

/**
 * How long a page's first flight into streets may take here. The first frames that draw the
 * street layers hold the page while the software renderer builds what it draws them with: 10 to
 * 20 s on a busy machine (Chrome's trace: the frame's commit waits in ReadPixels on
 * ContextVk::finishImpl), on top of the flight's own seconds. Later flights take seconds.
 */
const FIRST_FLIGHT_MS = 90_000;

/**
 * Resolves once the map has come to rest near a place. The map is waited for first: a linked
 * school's panel can show before MapLibre has loaded, and a poll that throws is not polled again.
 */
async function expectMapNear(
  page: Page,
  lat: number,
  lon: number,
  zoom: number,
  timeout = 30_000,
): Promise<void> {
  await page.waitForFunction(() => window.snowlightMap !== undefined, null, { timeout });
  await expect
    .poll(
      async () => {
        const view = await mapView(page);
        return (
          Math.abs(view.lat - lat) < 0.01 &&
          Math.abs(view.lon - lon) < 0.01 &&
          Math.abs(view.zoom - zoom) < 0.05
        );
      },
      { timeout },
    )
    .toBe(true);
}

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
}

// The default build: no data. -----------------------------------------------------------

test.describe('with no data shipped', () => {
  test('the glow is on the map, under every label and dark, and nothing under data/ is asked for', async ({
    browser,
    baseURL,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const { problems, requests } = watch(page);
    await page.goto('/');
    await waitForMap(page);
    const stats = await glowStats(page);
    // Empty, it holds nothing on the GPU either: no shaders are compiled until schools light up.
    expect(stats.mode).toBe('none');
    expect([stats.count, stats.glowCount]).toEqual([0, 0]);
    const order = await page.evaluate(() => window.snowlightMap?.getLayersOrder() ?? []);
    expect(order.indexOf(GLOW_LAYER)).toBeGreaterThan(0);
    expect(order.indexOf(GLOW_LAYER)).toBeLessThan(order.indexOf(FIRST_LABEL_LAYER));

    // The worker registers and the page settles: still nothing asked of data/ or of other sites.
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
      timeout: 30_000,
    });
    await page.waitForTimeout(1000);
    const origin = new URL(baseURL ?? '').origin;
    expect(requests.filter((url) => new URL(url).pathname.includes('/data/'))).toEqual([]);
    // MapLibre starts its workers from blob: URLs the page makes; they carry the site's origin.
    expect(
      requests.filter(
        (url) =>
          !url.startsWith(`${origin}/`) &&
          !url.startsWith(`blob:${origin}/`) &&
          !url.startsWith('data:'),
      ),
    ).toEqual([]);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('search takes text and shows nothing, says nothing, and loads no index', async ({
    browser,
  }) => {
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const { problems, requests } = watch(page);
      await page.goto('/');
      await waitForMap(page);
      const input = page.locator('input.search-input');
      await input.click();
      await input.pressSequentially('kansas city', { delay: 20 });
      await page.waitForTimeout(1500);
      await expect(input).toHaveValue('kansas city');
      await expect(input).toHaveAttribute('aria-expanded', 'false');
      await expect(page.locator('[role="listbox"], [role="option"], .results')).toHaveCount(0);
      await expect(page.locator('[role="status"]')).toHaveText('');
      await input.press('Enter');
      await page.waitForTimeout(300);
      expect(new URL(page.url()).search).toBe('');
      expect(requests.filter((url) => url.includes('search-index'))).toEqual([]);
      expect(page.workers().filter((worker) => !worker.url().startsWith('blob:'))).toEqual([]);
      // The clear button empties the field and keeps focus in it.
      await page.locator('button.search-clear').click();
      await expect(input).toHaveValue('');
      await expect(input).toBeFocused();
      expect(problems).toEqual([]);
      await context.close();
    }
  });

  test('the service worker registers only after the page has loaded, and takes the page', async ({
    browser,
  }) => {
    const context = await browser.newContext();
    // When the page loaded and when it first asked to register a worker, on the page's own clock.
    await context.addInitScript(() => {
      const times = { load: Number.NaN, register: Number.NaN };
      Object.assign(window, { swTimes: times });
      window.addEventListener('load', () => {
        times.load = performance.now();
      });
      const container = navigator.serviceWorker;
      const register = container.register.bind(container);
      container.register = (...args: Parameters<ServiceWorkerContainer['register']>) => {
        if (Number.isNaN(times.register)) times.register = performance.now();
        return register(...args);
      };
    });
    const page = await context.newPage();
    await page.goto('/');
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
      timeout: 30_000,
    });
    const times = await page.evaluate(
      () => (window as unknown as { swTimes: { load: number; register: number } }).swTimes,
    );
    expect(Number.isFinite(times.load)).toBe(true);
    expect(Number.isFinite(times.register)).toBe(true);
    expect(times.register).toBeGreaterThanOrEqual(times.load);
    expect(
      await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.scope),
    ).toBe(new URL('/', page.url()).href);
    await context.close();
  });

  test('a plain visit opens the pinned school without a history entry; a link keeps its own', async ({
    browser,
  }) => {
    const context = await browser.newContext();
    await context.addInitScript(
      ([key, school]) => {
        localStorage.setItem(key, JSON.stringify({ v: 1, school }));
      },
      [PIN_KEY, PEMBROKE_HILL] as const,
    );
    const page = await context.newPage();
    await page.goto('/');
    const before = await page.evaluate(() => history.length);
    await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL);
    expect(await page.evaluate(() => history.length)).toBe(before);

    // A shared view is what the sender saw: the pin does not replace it.
    await page.goto('/?at=39.045,-94.595,13.2');
    await waitForMap(page);
    await page.waitForTimeout(500);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();

    // A shared school opens that school, whatever is pinned.
    await page.goto('/?school=291640000557');
    await waitForMap(page);
    await page.waitForTimeout(500);
    expect(new URL(page.url()).searchParams.get('school')).toBe('291640000557');
    await context.close();
  });

  test('"/" goes to the search field; its key shows only with a keyboard, and no update time shows', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const { problems } = watch(page);
    await page.goto('/');
    await waitForMap(page);
    const input = page.locator('input.search-input');
    const key = page.locator('.search-key');
    await expect(key).toBeVisible();
    await expect(input).toHaveAttribute('aria-keyshortcuts', '/');

    // From the map: the field takes focus, nothing is typed, and the key steps aside.
    await page.mouse.click(720, 500);
    await expect(input).not.toBeFocused();
    await page.keyboard.press('/');
    await expect(input).toBeFocused();
    await expect(input).toHaveValue('');
    await expect(key).toHaveCSS('opacity', '0');
    // In the field, "/" is text like any other.
    await page.keyboard.type('a/b');
    await expect(input).toHaveValue('a/b');
    // Back on the map, "/" returns to the field with its text selected, ready to replace.
    await page.mouse.click(720, 500);
    await page.keyboard.press('/');
    await expect(input).toBeFocused();
    await page.keyboard.type('duluth');
    await expect(input).toHaveValue('duluth');

    // Nothing live is shown, so no time is given.
    await expect(page.locator('.updated, time')).toHaveCount(0);
    expect(problems).toEqual([]);
    await context.close();

    // A touch screen has no "/" key: the hint is not shown.
    const phone = await browser.newContext(devices['Pixel 7']);
    const touch = await phone.newPage();
    await touch.goto('/');
    await expect(touch.locator('input.search-input')).toBeVisible();
    await expect(touch.locator('.search-key')).toBeHidden();
    await phone.close();
  });

  test('the build holds no data, and nothing made up', () => {
    const dist = path.join(WEB, 'dist');
    const files = filesIn(dist);
    expect(files.filter((file) => file.startsWith('data/'))).toEqual([]);
    const flagged = files.filter((file) =>
      SYNTHETIC_MARKERS.test(readFileSync(path.join(dist, file)).toString('latin1')),
    );
    expect(flagged).toEqual([]);
  });

  test('the wordmark is marked for masking, and the shell reads from the copy', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(page.locator('h1.wordmark')).toHaveAttribute('data-brand', '');
    await expect(page.locator('h1.wordmark')).toHaveText(copy.appName);
    await expect(page.locator('input.search-input')).toHaveAttribute(
      'placeholder',
      copy.search.placeholder,
    );
  });
});

// A build with data staged. ------------------------------------------------------------

/**
 * Real records (September 2026): the cities and the ZIP code as
 * pipeline/out/site-data/search has them, the schools as search records made
 * from their names and places in pipeline/out/site-data/schools.
 */
const SEARCH_RECORDS = [
  '{"geoid":"2036000","kind":"city","lat":39.122539,"lon":-94.741781,"name":"Kansas City","population":157805,"state":"KS"}',
  '{"geoid":"2938000","kind":"city","lat":39.125155,"lon":-94.550313,"name":"Kansas City","population":521220,"state":"MO"}',
  '{"districts":[{"leaid":"2916400","name":"Kansas City 33 School District","share":1.0}],"lat":39.01414,"lon":-94.595493,"states":["MO"],"zcta":"64113"}',
  '{"kind":"school","id":"291640000557","name":"BORDER STAR MONTESSORI","sub":"","state":"MO","lat":39.013304,"lon":-94.592692,"weight":0}',
  '{"kind":"school","id":"A1902690","name":"THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS","sub":"","state":"MO","lat":39.03606,"lon":-94.593001,"weight":0}',
];

/** Those two schools as the pipeline's directory has them (schools/meta.json, points.bin). */
const DIRECTORY_SCHOOLS = [
  {
    id: '291640000557',
    name: 'BORDER STAR MONTESSORI',
    lon: -94.592692,
    lat: 39.013304,
    district: 0,
    kind: 0,
  },
  {
    id: PEMBROKE_HILL,
    name: 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
    lon: -94.593001,
    lat: 39.03606,
    district: 0xffffffff,
    kind: 1,
  },
] as const;
const DIRECTORY_ON = '2026-09-25';

function directoryMeta(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: DIRECTORY_ON,
    count: DIRECTORY_SCHOOLS.length,
    ids: DIRECTORY_SCHOOLS.map((school) => school.id),
    names: DIRECTORY_SCHOOLS.map((school) => school.name),
    districts: { ids: ['2916400'], names: ['KANSAS CITY 33'] },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

function directoryPoints(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * DIRECTORY_SCHOOLS.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(DIRECTORY_SCHOOLS.length, 8);
  bytes.writeUInt32LE(1, 12);
  DIRECTORY_SCHOOLS.forEach((school, i) => {
    const at = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), at);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), at + 4);
    bytes.writeUInt32LE(school.district, at + 8);
    bytes.writeUInt8(school.kind, at + 12);
  });
  return bytes;
}

/**
 * Those two schools as the directory's own tables list them (the detail files
 * scripts/stage-data.mjs writes, src/data/details-format.ts), one shard and its index.
 */
function directoryDetails(): { index: string; shard: string } {
  const directory = { generated_on: DIRECTORY_ON, schools: 2, districts: 1 };
  const rows = [
    [
      '291640000557',
      'BORDER STAR MONTESSORI',
      0,
      0,
      '2916400',
      'KANSAS CITY 33',
      '6321 WORNALL RD',
      'KANSAS CITY',
      'MO',
      '64113',
      'Jackson County',
      'PK',
      '06',
      251,
      '8164185150',
      [[1, PEMBROKE_HILL, 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS', 2530, -94.593001, 39.03606]],
    ],
    [
      PEMBROKE_HILL,
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      1,
      null,
      null,
      null,
      '400 W 51ST ST',
      'KANSAS CITY',
      'MO',
      '64112',
      'Jackson County',
      'PK',
      '12',
      1174,
      '8169361230',
      [[0, '291640000557', 'BORDER STAR MONTESSORI', 2530, -94.592692, 39.013304]],
    ],
  ];
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory,
      shards: 1,
      first_ids: ['291640000557'],
      files: ['0.json'],
    }),
    shard: JSON.stringify({ schema_version: 1, directory, first: 0, rows }),
  };
}

/** SYNTHETIC: made-up statuses for the two schools, for this test only. */
const SYNTHETIC_DAY = '2026-01-12';
const SYNTHETIC_NOW = new Date('2026-01-12T18:00:00Z');
function syntheticClosings(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:42:00Z',
    directory: { generated_on: DIRECTORY_ON, schools: 2, districts: 1 },
    days: [
      {
        day: SYNTHETIC_DAY,
        gaps: [0, 0],
        statuses: [0, 1],
        announced: [98, 40],
        reasons: [0, 1],
        shifts: [120],
        clocks: [null],
      },
    ],
  });
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address !== null ? address.port : 0;
      server.close(() => {
        resolve(port);
      });
    });
  });
}

test.describe('with data staged', () => {
  // One build, shared by the tests below, which run in order in one worker.
  test.describe.configure({ mode: 'default' });
  let root = '';
  let server: PreviewServer | undefined;
  let site = '';

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    if (test.info().project.name !== 'desktop') return;
    root = mkdtempSync(path.join(tmpdir(), 'snowlight-app-e2e-'));
    const publicDir = path.join(root, 'public');
    // The app's own public files, then the staged data.
    for (const file of filesIn(path.join(WEB, 'public'))) {
      if (file.startsWith('data/')) continue;
      mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
      writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
    }
    const data = path.join(publicDir, 'data');
    mkdirSync(path.join(data, 'schools'), { recursive: true });
    mkdirSync(path.join(data, 'live'), { recursive: true });
    const records = path.join(root, 'records.jsonl');
    writeFileSync(records, `${SEARCH_RECORDS.join('\n')}\n`);
    execFileSync(
      process.execPath,
      ['scripts/build-search-index.mjs', '--out', path.join(data, 'search-index.bin'), records],
      { cwd: WEB, stdio: 'pipe' },
    );
    writeFileSync(path.join(data, 'schools/meta.json'), directoryMeta());
    writeFileSync(path.join(data, 'schools/points.bin'), directoryPoints());
    writeFileSync(path.join(data, 'live/closings.json'), syntheticClosings());
    mkdirSync(path.join(data, 'schools/details'), { recursive: true });
    const details = directoryDetails();
    writeFileSync(path.join(data, 'schools/details/index.json'), details.index);
    writeFileSync(path.join(data, 'schools/details/0.json'), details.shard);
    // Staged as the pipeline writes it: its own records sit next to the outputs, never published.
    writeFileSync(path.join(data, 'schools/manifest.internal.json'), '{}');
    writeFileSync(path.join(data, '.gitkeep'), '');

    const outDir = path.join(root, 'site');
    await build({
      root: WEB,
      publicDir,
      // A cache of its own, so this build never races another spec's.
      cacheDir: path.join(root, 'vite-cache'),
      logLevel: 'warn',
      build: { outDir, emptyOutDir: true },
    });
    const port = await freePort();
    server = await preview({
      root: WEB,
      logLevel: 'warn',
      build: { outDir },
      preview: { host: '127.0.0.1', port, strictPort: true },
    });
    site = `http://127.0.0.1:${String(port)}/`;
  });

  test.afterAll(async () => {
    await server?.close();
    if (root !== '') rmSync(root, { recursive: true, force: true });
  });

  test('the staged build ships exactly its published files, none of the pipeline’s own', () => {
    const shipped = filesIn(path.join(root, 'site', 'data')).sort();
    expect(shipped).toEqual([
      'live/closings.json',
      'schools/details/0.json',
      'schools/details/index.json',
      'schools/meta.json',
      'schools/points.bin',
      'search-index.bin',
    ]);
    expect(statSync(path.join(root, 'site', 'data', 'search-index.bin')).size).toBeGreaterThan(0);
  });

  test('search loads the index on first focus, lists results, and a pick takes the map there', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const { problems, requests } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    // A data file the page loads before the service worker takes over is fetched once more,
    // through the worker, for offline use (src/pwa/data.ts warmDataCache): search starts here
    // once the worker is in control, so the index is fetched once, through it.
    await page.evaluate(async () => {
      const worker = (
        window as unknown as {
          snowlightServiceWorker?: Promise<{ warmed: Promise<number> } | null>;
        }
      ).snowlightServiceWorker;
      await (
        await worker
      )?.warmed;
    });
    await page.waitForTimeout(500);
    const indexRequests = (): string[] => requests.filter((url) => url.includes('search-index'));
    expect(indexRequests()).toEqual([]);

    const input = page.locator('input.search-input');
    await input.click();
    await expect.poll(() => indexRequests().length).toBe(1);
    await input.pressSequentially('kansas city', { delay: 20 });
    const options = page.locator('[role="option"]');
    await expect(options).toHaveCount(2);
    await expect(options.nth(0)).toContainText('Kansas City');
    await expect(options.nth(0)).toContainText('Missouri');
    // Each kind of result is a group under its heading; the places come first.
    const groups = page.locator('[role="listbox"] > [role="group"]');
    await expect(groups).toHaveCount(1);
    await expect(groups.nth(0)).toHaveAccessibleName(copy.search.sections.city);
    await expect(groups.nth(0).locator('[role="option"]')).toHaveCount(2);
    await expect(input).toHaveAttribute('aria-expanded', 'true');
    await expect(input).toHaveAttribute('aria-controls', 'search-results');

    // The best match is highlighted as the results come; keys move through the list, around
    // its ends; Enter picks, and the map goes to the city.
    await expect(input).toHaveAttribute('aria-activedescendant', 'search-results-0');
    await expect(options.nth(0)).toHaveAttribute('aria-selected', 'true');
    await input.press('ArrowDown');
    await expect(input).toHaveAttribute('aria-activedescendant', 'search-results-1');
    await expect(options.nth(0)).toHaveAttribute('aria-selected', 'false');
    await expect(options.nth(1)).toHaveAttribute('aria-selected', 'true');
    await input.press('ArrowDown');
    await expect(input).toHaveAttribute('aria-activedescendant', 'search-results-0');
    await input.press('ArrowUp');
    await input.press('ArrowUp');
    await expect(input).toHaveAttribute('aria-activedescendant', 'search-results-0');
    await input.press('Enter');
    await expect(input).toHaveValue('Kansas City');
    await expect(page.locator('[role="listbox"]')).toHaveCount(0);
    await expectMapNear(page, 39.125155, -94.550313, 11);

    // A ZIP code opens as a selection of its own.
    await input.click();
    await input.fill('');
    await input.pressSequentially('64113', { delay: 20 });
    await expect(options).toHaveCount(1);
    await expect(groups.nth(0)).toHaveAccessibleName(copy.search.sections.zip);
    await options.nth(0).click();
    await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64113');
    await expectMapNear(page, 39.01414, -94.595493, 12);

    // The school: its link, and the map at street level on it.
    await input.click();
    await input.fill('');
    await input.pressSequentially('pembroke', { delay: 20 });
    await expect(options).toHaveCount(1);
    // The directory writes this name in capitals; it shows in title case.
    await expect(options.nth(0)).toContainText('The Pembroke Hill School - Wornall Campus');
    await expect(options.nth(0).locator('b')).toHaveText('Pembroke');
    await expect(groups.nth(0)).toHaveAccessibleName(copy.search.sections.school);
    await options.nth(0).click();
    await expect(input).toHaveValue('The Pembroke Hill School - Wornall Campus');
    await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL);
    await expectMapNear(page, 39.03606, -94.593001, 15);

    // Text that matches nothing says so, plainly.
    await input.click();
    await input.fill('');
    await input.pressSequentially('qqqzzx', { delay: 20 });
    await expect(page.locator('.results')).toHaveText(copy.search.noResults);
    await expect(page.locator('[role="status"]')).toHaveText(copy.search.noResults);
    await expect(input).toHaveAttribute('aria-expanded', 'false');
    // Escape hides it and keeps the text; a second Escape clears the field.
    await input.press('Escape');
    await expect(page.locator('.results')).toHaveCount(0);
    await expect(page.locator('[role="status"]')).toHaveText('');
    await expect(input).toHaveValue('qqqzzx');
    await expect(input).toBeFocused();
    await input.press('Escape');
    await expect(input).toHaveValue('');
    await expect(input).toBeFocused();
    expect(indexRequests()).toHaveLength(1);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the first Escape hides the list and keeps the text; the second clears it', async ({
    browser,
  }) => {
    for (const options of [
      { viewport: { width: 1440, height: 900 } },
      // A phone, as Chrome on Android sees the page: touch, mobile viewport.
      devices['Pixel 7'],
    ]) {
      const context = await browser.newContext(options);
      const page = await context.newPage();
      const { problems } = watch(page);
      await page.goto(site);
      await waitForMap(page);
      const input = page.locator('input.search-input');
      const listed = page.locator('[role="option"]');
      const typeInto = async (text: string): Promise<void> => {
        await input.click();
        await input.fill('');
        await input.pressSequentially(text, { delay: 20 });
      };

      await typeInto('kansas city');
      await expect(listed).toHaveCount(2);
      const url = page.url();
      await input.press('Escape');
      await expect(listed).toHaveCount(0);
      await expect(input).toHaveValue('kansas city');
      await expect(input).toHaveAttribute('aria-expanded', 'false');
      await expect(input).toBeFocused();
      // Down brings the list back as it was; Escape hides it again, and the text stays.
      await input.press('ArrowDown');
      await expect(listed).toHaveCount(2);
      await expect(input).toHaveAttribute('aria-expanded', 'true');
      await input.press('Escape');
      await expect(listed).toHaveCount(0);
      await expect(input).toHaveValue('kansas city');
      // Nothing was picked: the address and the history are as they were.
      expect(page.url()).toBe(url);
      // The second Escape clears the field, and focus stays in it.
      await input.press('Escape');
      await expect(input).toHaveValue('');
      await expect(input).toBeFocused();

      // After a pick, coming back to the field lists its results again; Escape keeps the text.
      await typeInto('64113');
      await expect(listed).toHaveCount(1);
      await listed.first().click();
      await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64113');
      await expect(input).not.toBeFocused();
      const picked = await input.inputValue();
      expect(picked).toContain('64113');
      await input.click();
      await expect(listed).toHaveCount(1);
      await input.press('Escape');
      await expect(listed).toHaveCount(0);
      await expect(input).toHaveValue(picked);
      // Leaving the field and coming back shows the results Escape hid.
      await input.blur();
      await input.click();
      await expect(listed).toHaveCount(1);
      await input.press('Escape');
      await input.press('Escape');
      await expect(input).toHaveValue('');
      expect(new URL(page.url()).searchParams.get('zip')).toBe('64113');
      expect(problems).toEqual([]);
      await context.close();
    }
  });

  test('each pick is a step: Back goes from a city to the ZIP code before it, then to the start', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    const { problems } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    const start = await mapView(page);
    const entries = await page.evaluate(() => history.length);
    const search = (): URLSearchParams => new URL(page.url()).searchParams;

    const input = page.locator('input.search-input');
    const options = page.locator('[role="option"]');
    const pickFirst = async (text: string): Promise<void> => {
      await input.click();
      await input.fill('');
      await input.pressSequentially(text, { delay: 20 });
      await expect(options.first()).toBeVisible();
      await options.first().click();
    };

    await pickFirst('64113');
    await expect.poll(() => search().get('zip')).toBe('64113');
    await expectMapNear(page, 39.01414, -94.595493, 12);
    await pickFirst('kansas city');
    await expect.poll(() => search().get('zip')).toBeNull();
    await expectMapNear(page, 39.125155, -94.550313, 11);
    expect(search().get('at')).toBe('39.1252,-94.5503,11');
    expect(await page.evaluate(() => history.length)).toBe(entries + 2);

    await expect(input).toHaveValue('Kansas City');

    // Back: the ZIP code again, where it was, and the field no longer names the city.
    await page.goBack();
    await expect.poll(() => search().get('zip')).toBe('64113');
    await expectMapNear(page, 39.0141, -94.5955, 12);
    await expect(input).toHaveValue('');
    // Back again: the start, still in the app.
    await page.goBack();
    await expect.poll(() => page.url()).toBe(site);
    await expectMapNear(page, start.lat, start.lon, start.zoom);
    // Forward twice: the city.
    await page.goForward();
    await expect.poll(() => search().get('zip')).toBe('64113');
    await page.goForward();
    await expect.poll(() => search().get('at')).toBe('39.1252,-94.5503,11');
    await expectMapNear(page, 39.1252, -94.5503, 11);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('a link to a school, or the pinned school, opens there', async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    const { problems } = watch(page);
    await page.goto(`${site}?school=291640000557`);
    await waitForMap(page);
    await expectMapNear(page, 39.013304, -94.592692, 15);
    await expect.poll(() => new URL(page.url()).searchParams.get('at')).not.toBeNull();

    await page.addInitScript(
      ([key, school]) => {
        localStorage.setItem(key, JSON.stringify({ v: 1, school }));
      },
      [PIN_KEY, PEMBROKE_HILL] as const,
    );
    await page.goto(site);
    await waitForMap(page);
    await expectMapNear(page, 39.03606, -94.593001, 15);
    expect(new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('a picked school lands in its panel: its day from the live file, what it is, pin, share and close', async ({
    browser,
  }) => {
    // Two first flights into streets, one a page (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: 'America/Chicago',
      permissions: ['clipboard-read', 'clipboard-write'],
    });
    const page = await context.newPage();
    // Its calendar alone: the flights below and the share button's timer run in real time.
    await fixDate(page, SYNTHETIC_NOW);
    const { problems } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    const input = page.locator('input.search-input');
    await input.click();
    await input.pressSequentially('pembroke', { delay: 20 });
    await page.locator('[role="option"]').first().click();

    const panel = page.locator('aside.detail');
    await expect(panel).toHaveAccessibleName(copy.detail.label);
    await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect(panel.locator('.kind')).toHaveText(`${copy.detail.privateSchool} · PK–12`);
    await expect(panel.locator('.place')).toHaveText('Kansas City, MO · Jackson County');
    // SYNTHETIC statuses: delayed today, as the made-up live file says, and nothing made up here.
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.delayed.today]);
    await expect(panel.locator('.status .line-detail')).toHaveText(format.delay(120, null) ?? '');
    await expect(panel.locator('.status .line-note')).toHaveText(
      `${copy.reason.ice} · ${format.posted(new Date('2026-01-12T12:02:00Z'), 'America/Chicago', SYNTHETIC_NOW)}`,
    );
    await expect(panel.locator('.status .glyph.is-delayed')).toHaveCount(1);
    // A private school has no district history to give a chance: there is no chance card.
    await expect(panel.locator('.outlook')).toHaveCount(0);
    await expect(panel.locator('.fact dt')).toHaveText([
      copy.detail.students,
      copy.detail.address,
      copy.detail.phone,
    ]);
    await expect(panel.locator('.fact a')).toHaveAttribute('href', 'tel:+18169361230');
    // The school nearest it, keyed with its status today (SYNTHETIC: closed).
    await expect(panel.locator('.near-name')).toHaveText(['Border Star Montessori']);
    await expect(panel.locator('.near-distance')).toHaveText([format.miles(2530)]);
    await expect(panel.locator('.near .glyph.is-closed')).toHaveCount(1);
    // After a pick the panel has the focus.
    await expect(panel).toBeFocused();
    // The map lands on the school: the share button's timer below then runs on a page at rest.
    await expectMapNear(page, 39.03606, -94.593001, 15, FIRST_FLIGHT_MS);

    const [pin, share] = [panel.locator('.action').nth(0), panel.locator('.action').nth(1)];
    await pin.click();
    await expect(pin).toHaveAttribute('aria-pressed', 'true');
    await expect(pin).toHaveText(copy.pin.mySchool);
    expect(await page.evaluate((key) => localStorage.getItem(key), PIN_KEY)).toBe(
      JSON.stringify({ v: 1, school: PEMBROKE_HILL }),
    );
    await share.click();
    await expect(share).toHaveText(copy.share.copied);
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      `${site}?school=${PEMBROKE_HILL}`,
    );
    // Back to Share once the button's own time is up, with a moment's slack for a busy page.
    await expect(share).toHaveText(copy.actions.share, { timeout: COPIED_MS + 3000 });

    // Escape closes it: the school leaves the address.
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();

    // A link to a public school opens its panel too: closed today, with its district.
    await page.goto(`${site}?school=291640000557`);
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.closed.today]);
    await expect(panel.locator('.status .glyph.is-closed')).toHaveCount(1);
    await expect(panel.locator('.fact dt').first()).toHaveText(copy.detail.district);
    await expect(panel.locator('.fact dd').first()).toHaveText('Kansas City 33');
    // It lands there first, as a link does: the nearby school below is picked from its streets.
    await expectMapNear(page, 39.013304, -94.592692, 15, FIRST_FLIGHT_MS);
    // Its nearest school opens from the list: the map goes there, and its panel takes this one's place.
    await panel.locator('.near').first().click();
    await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL);
    await expectMapNear(page, 39.03606, -94.593001, 15);
    await panel.locator('.close').click();
    await expect(panel).toHaveCount(0);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('on a phone a school opens in a sheet half up, over the map with the school in the middle of what it leaves, and the sheet drags', async ({
    browser,
  }) => {
    const context = await browser.newContext({
      ...devices['Pixel 7'],
      timezoneId: 'America/Chicago',
    });
    const page = await context.newPage();
    const { problems } = watch(page);
    const touch = await context.newCDPSession(page);
    /** A finger put down at (x, from), moved to (x, to) over `ms`, and lifted. */
    const drag = async (x: number, from: number, to: number, ms: number): Promise<void> => {
      await touch.send('Input.dispatchTouchEvent', {
        type: 'touchStart',
        touchPoints: [{ x, y: from }],
      });
      const steps = Math.max(2, Math.round(ms / 16));
      for (let step = 1; step <= steps; step++) {
        await touch.send('Input.dispatchTouchEvent', {
          type: 'touchMove',
          touchPoints: [{ x, y: from + ((to - from) * step) / steps }],
        });
        await page.waitForTimeout(16);
      }
      await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    };
    const { width, height } = page.viewportSize() ?? { width: 0, height: 0 };
    const sheet = page.locator('aside.detail');
    const grip = sheet.locator('.grip');
    const sheetTop = async (): Promise<number> => (await sheet.boundingBox())?.y ?? Number.NaN;
    const opensAt = height - Math.round(height / 2);

    // A link with no view: the map goes to the school, which lands on its streets in the middle
    // of the map between the search field and the sheet, as a search pick lands.
    await page.goto(`${site}?school=${PEMBROKE_HILL}`);
    await expect(sheet.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect(grip).toHaveAttribute('aria-expanded', 'false');
    const barBottom = await page
      .locator('.bar')
      .evaluate((bar) => bar.getBoundingClientRect().bottom);
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    await expect
      .poll(() => new URL(page.url()).searchParams.get('at'), { timeout: 30_000 })
      .not.toBeNull();
    const school = await page.evaluate(() => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const point = map.project([-94.593001, 39.03606]);
      return { x: point.x, y: point.y, zoom: map.getZoom() };
    });
    expect(school.zoom).toBeCloseTo(15, 1);
    expect(Math.abs(school.x - width / 2)).toBeLessThan(4);
    expect(Math.abs(school.y - (barBottom + opensAt) / 2)).toBeLessThan(4);

    // Down by the grip: the name alone, and the most of the map in view.
    await drag(width / 2, opensAt + 12, height - 200, 400);
    await expect(sheet).toHaveAttribute('data-detent', 'peek');
    await expect.poll(sheetTop).toBeGreaterThan(height - 260);
    const peekTop = await sheetTop();
    const name = await sheet.locator('h2').boundingBox();
    expect((name?.y ?? height) + (name?.height ?? 0)).toBeLessThan(height);
    // Up by the name, most of the way: open again.
    await drag(width / 2, peekTop + 40, opensAt + 60, 400);
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    // The grip takes it up to just under the search field, and says so.
    await grip.tap();
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    await expect(grip).toHaveAttribute('aria-expanded', 'true');
    await expect(grip).toHaveAttribute('aria-label', copy.detail.less);
    await expect.poll(sheetTop).toBeCloseTo(barBottom + 12, 0);
    // Dragged down by the name, even at full height: open.
    const named = await sheet.locator('h2').boundingBox();
    const nameY = (named?.y ?? 0) + 8;
    await drag(width / 2, nameY, nameY + 220, 300);
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    // Its buttons take a tap: a thumb's height, and the pin pins.
    const pin = sheet.locator('.action').first();
    expect((await pin.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    await pin.tap();
    await expect(pin).toHaveAttribute('aria-pressed', 'true');
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    // Pulled down past the name, it goes, and the school leaves the address.
    await drag(width / 2, opensAt + 12, height - 8, 300);
    await expect(sheet).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();

    // On the made-up storm day: the answer (today's status and the chance of a closure) is above
    // the fold as the sheet opens, and the buttons come after it.
    const stormy = await context.newPage();
    const stormProblems = watch(stormy).problems;
    await stormy.clock.setFixedTime(SYNTHETIC_NOW);
    await stormy.goto(`${site}?school=${PEMBROKE_HILL}&at=39.0334,-94.593,15`);
    const panel = stormy.locator('aside.detail');
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.delayed.today]);
    await expect(panel).toHaveAttribute('data-detent', 'open');
    await expect.poll(async () => (await panel.boundingBox())?.y).toBeCloseTo(opensAt, 0);
    const bottomOf = async (selector: string): Promise<number> => {
      const box = await panel.locator(selector).boundingBox();
      return (box?.y ?? Number.POSITIVE_INFINITY) + (box?.height ?? 0);
    };
    expect(await bottomOf('.head')).toBeLessThan(height);
    expect(await bottomOf('.status')).toBeLessThan(height);
    // A private school has no district history to give a chance: no chance card.
    await expect(panel.locator('.outlook')).toHaveCount(0);
    expect((await panel.locator('.actions').boundingBox())?.y).toBeGreaterThan(
      await bottomOf('.status'),
    );
    // Its close button: the sheet glides away, and the school leaves the address.
    await panel.locator('.close').tap();
    await expect(panel).toHaveCount(0);
    expect(new URL(stormy.url()).searchParams.get('school')).toBeNull();
    expect(problems).toEqual([]);
    expect(stormProblems).toEqual([]);
    await context.close();
  });

  test('the update time is the live file’s own time: live while recent, then when it was updated', async ({
    browser,
  }) => {
    const zone = 'America/Chicago';
    const generated = new Date('2026-01-12T12:42:00Z');
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      const context = await browser.newContext({ viewport, timezoneId: zone });
      const page = await context.newPage();
      // Eight minutes after the file was made.
      await page.clock.setFixedTime(new Date('2026-01-12T12:50:00Z'));
      const { problems } = watch(page);
      await page.goto(site);
      await waitForMap(page);
      const updated = page.locator('.updated');
      await expect(updated).toHaveText(format.liveAt(generated, zone), { timeout: 30_000 });
      await expect(updated.locator('time')).toHaveAttribute('datetime', '2026-01-12T12:42:00Z');
      await expect(updated.locator('.dot')).toHaveCount(1);

      // On the search field's line at the right edge; on a phone, across from the wordmark,
      // over the field's right end.
      const line = await updated.boundingBox();
      const field = await page.locator('.search').boundingBox();
      const name = await page.locator('h1.wordmark').boundingBox();
      if (line === null || field === null || name === null) throw new Error('no box');
      if (viewport.width >= 720) {
        expect(Math.abs(line.y + line.height / 2 - (field.y + field.height / 2))).toBeLessThan(1);
        expect(Math.abs(viewport.width - 20 - (line.x + line.width))).toBeLessThan(3);
        expect(line.x).toBeGreaterThan(field.x + field.width + 100);
      } else {
        expect(Math.abs(line.y + line.height / 2 - (name.y + name.height / 2))).toBeLessThan(1);
        expect(line.y + line.height).toBeLessThanOrEqual(field.y);
        expect(line.x + line.width).toBeLessThanOrEqual(field.x + field.width);
        expect(field.x + field.width - (line.x + line.width)).toBeLessThan(8);
        expect(line.x).toBeGreaterThan(name.x + name.width + 24);
      }

      // Offline, it says so, and keeps the file's time.
      await context.setOffline(true);
      await expect(updated).toHaveText(
        format.offline(generated, zone, new Date('2026-01-12T12:50:00Z')),
      );
      await expect(updated.locator('.dot')).toHaveCount(0);
      await context.setOffline(false);
      await expect(updated).toHaveText(format.liveAt(generated, zone));
      expect(problems).toEqual([]);
      await context.close();
    }

    // That afternoon the same file is no longer live: the line says when it was updated.
    const later = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: zone,
    });
    const page = await later.newPage();
    await page.clock.setFixedTime(SYNTHETIC_NOW);
    await page.goto(site);
    await waitForMap(page);
    const updated = page.locator('.updated');
    await expect(updated).toHaveText(format.updatedAt(generated, zone, SYNTHETIC_NOW), {
      timeout: 30_000,
    });
    await expect(updated.locator('.dot')).toHaveCount(0);
    await later.close();
  });

  test('the update time at its longest keeps beside the field, and the list opens under it', async ({
    browser,
  }) => {
    const zone = 'America/Chicago';
    const generated = new Date('2026-01-12T12:42:00Z');
    // The next day, so the line names the file's day; offline too, it runs longest.
    const nextDay = new Date('2026-01-13T15:00:00Z');

    /** The line's words right of the field and clear of it, inside the strip, ending at its edge. */
    async function besideField(page: Page, width: number, where: string): Promise<void> {
      const field = await page.locator('.search').boundingBox();
      if (field === null) throw new Error('no field');
      const words = await page.locator('.updated time').evaluate((time) => {
        const range = document.createRange();
        range.selectNodeContents(time);
        const { left, right, top, bottom } = range.getBoundingClientRect();
        return { left, right, top, bottom, clipped: time.scrollWidth > time.clientWidth };
      });
      expect(words.left, where).toBeGreaterThanOrEqual(field.x + field.width + 12);
      expect(Math.abs(width - 20 - words.right), where).toBeLessThan(4);
      expect(words.top, where).toBeGreaterThanOrEqual(field.y);
      expect(words.bottom, where).toBeLessThanOrEqual(field.y + field.height);
      expect(words.clipped, where).toBe(false);
    }

    for (const viewport of [
      { width: 720, height: 900 },
      { width: 800, height: 900 },
      { width: 1024, height: 768 },
      { width: 844, height: 390 },
    ]) {
      const where = `${String(viewport.width)}x${String(viewport.height)}`;
      const context = await browser.newContext({ viewport, timezoneId: zone });
      const page = await context.newPage();
      await page.clock.setFixedTime(nextDay);
      const { problems } = watch(page);
      await page.goto(site);
      await waitForMap(page);

      // The results list runs under the field, as wide as it.
      const input = page.locator('.search-input');
      await input.click();
      await input.pressSequentially('kansas city', { delay: 20 });
      await expect(page.locator('.results [role="option"]').first()).toBeVisible();
      const field = await page.locator('.search').boundingBox();
      const list = await page.locator('.results').boundingBox();
      if (field === null || list === null) throw new Error('no box');
      expect(Math.abs(list.x - field.x), where).toBeLessThan(0.5);
      expect(Math.abs(list.width - field.width), where).toBeLessThan(0.5);
      expect(list.y, where).toBeGreaterThan(field.y + field.height);
      await input.press('Escape');
      await input.press('Escape');

      const updated = page.locator('.updated');
      await expect(updated).toHaveText(format.updatedAt(generated, zone, nextDay), {
        timeout: 30_000,
      });
      await besideField(page, viewport.width, where);
      await context.setOffline(true);
      await expect(updated).toHaveText(format.offline(generated, zone, nextDay));
      await besideField(page, viewport.width, `${where}, offline`);
      await context.setOffline(false);
      expect(problems).toEqual([]);
      await context.close();
    }
  });

  test('today’s schools glow, read from the live file against the directory', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.clock.setFixedTime(SYNTHETIC_NOW);
    const { problems, requests } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    await expect.poll(async () => (await glowStats(page)).glowCount, { timeout: 30_000 }).toBe(2);
    await expect.poll(async () => (await glowStats(page)).mode).toBe('float');
    const closings = requests.filter((url) => url.endsWith('/data/live/closings.json'));
    expect(closings.length).toBeGreaterThanOrEqual(1);

    // The legend counts the schools lit in each status, and dims a status with none; nothing
    // on the page moves as the counts come.
    const legend = page.locator('ul.legend');
    await expect(legend.locator('li')).toHaveText([
      `${copy.status.closed} ${format.number(1)}`,
      `${copy.status.delayed} ${format.number(1)}`,
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    await expect(legend.locator('li.is-none')).toHaveText([
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    await expect(legend.locator('.count')).toHaveText([format.number(1), format.number(1)]);
    expect(await layoutShifts(page)).toEqual([]);
    expect(problems).toEqual([]);

    // The day after, the same file lights nothing.
    const later = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const next = await later.newPage();
    await next.clock.setFixedTime(new Date('2026-01-13T18:00:00Z'));
    const nextWatch = watch(next);
    await next.goto(site);
    await waitForMap(next);
    await expect
      .poll(() => nextWatch.requests.filter((url) => url.endsWith('/data/live/closings.json')))
      .not.toEqual([]);
    await next.waitForTimeout(2000);
    expect((await glowStats(next)).glowCount).toBe(0);
    // Nothing lit, nothing counted: the legend is the key alone.
    await expect(next.locator('ul.legend li')).toHaveText(
      STATUS_KEYS.map((key) => copy.status[key]),
    );
    await expect(next.locator('ul.legend .count')).toHaveCount(0);
    await expect(next.locator('ul.legend li.is-none')).toHaveCount(0);
    expect(nextWatch.problems).toEqual([]);
    await later.close();
    await context.close();
  });

  test('a click on two lights at the national view zooms in toward them; one alone opens as a search pick does', async ({
    browser,
  }) => {
    // Two first flights into streets, one a page (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: 'America/Chicago',
    });
    const page = await context.newPage();
    // Its calendar alone: the flights and the click's wait for a second click run in real time.
    await fixDate(page, SYNTHETIC_NOW);
    const { problems } = watch(page);
    const panel = page.locator('aside.detail');
    const input = page.locator('input.search-input');
    const cursor = (): Promise<string> =>
      page.evaluate(() => {
        const canvas = document.querySelector('.maplibregl-canvas');
        return canvas === null ? '' : getComputedStyle(canvas).cursor;
      });
    /** Where the map lands for Border Star once its panel is open, as the address and the screen say. */
    const landing = async (): Promise<number[]> => {
      const barBottom = await page
        .locator('.bar')
        .evaluate((bar) => bar.getBoundingClientRect().bottom);
      const panelRight = await panel.evaluate((aside) => aside.getBoundingClientRect().right);
      // At street level, with the school in the middle of what the panel leaves in view.
      await expect
        .poll(
          async () => {
            const view = await mapView(page);
            const school = await onScreen(page, BORDER_STAR);
            return (
              Math.abs(view.zoom - 15) < 0.01 &&
              Math.abs(school.x - (panelRight + 1440) / 2) < 2 &&
              Math.abs(school.y - (barBottom + 900) / 2) < 2
            );
          },
          { timeout: FIRST_FLIGHT_MS },
        )
        .toBe(true);
      await settleMap(page);
      const at = (new URL(page.url()).searchParams.get('at') ?? '').split(',').map(Number);
      const school = await onScreen(page, BORDER_STAR);
      return [...at, school.x, school.y];
    };

    // Picked in search, from the national view.
    await page.goto(site);
    await waitForMap(page);
    await input.click();
    await input.pressSequentially('border star', { delay: 20 });
    await page.locator('[role="option"]').first().click();
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    const picked = await landing();

    // Clicked on the national view, where the two schools' lights are under a pixel apart: a
    // click a few pixels under Border Star's could mean either, so it opens neither. The map
    // zooms in toward them instead, to where they stand apart.
    await page.goto(site);
    await waitForMap(page);
    await expect.poll(async () => (await glowStats(page)).glowCount, { timeout: 30_000 }).toBe(2);
    const national = await mapView(page);
    expect(national.zoom).toBeLessThan(5);
    const light = await onScreen(page, BORDER_STAR);
    const click = { x: Math.round(light.x), y: Math.round(light.y) + 3 };
    await page.mouse.move(click.x, click.y);
    await expect.poll(cursor).toBe('pointer');
    await page.mouse.move(click.x + 60, click.y);
    await expect.poll(cursor).toBe('grab');
    await page.mouse.click(click.x, click.y);
    await expect
      .poll(async () => (await mapView(page)).zoom, { timeout: FIRST_FLIGHT_MS })
      .toBeGreaterThan(10.9);
    await settleMap(page);
    expect((await mapView(page)).zoom).toBeLessThan(11.01);
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
    // Both tens of pixels apart now, around the middle of the part of the map a school's panel
    // leaves in view, as a pick frames its school: right of the panel, under the search strip.
    const star = await onScreen(page, BORDER_STAR);
    const hill = await onScreen(page, PEMBROKE_HILL_PLACE);
    expect(Math.hypot(star.x - hill.x, star.y - hill.y)).toBeGreaterThan(30);
    const strip = await page.locator('.bar').evaluate((bar) => bar.getBoundingClientRect().bottom);
    const open = { left: PANEL_RIGHT, top: strip, right: 1440, bottom: 900 };
    const middle = { x: (open.left + open.right) / 2, y: (open.top + open.bottom) / 2 };
    for (const place of [star, hill]) {
      expect(place.x).toBeGreaterThan(open.left);
      expect(place.y).toBeGreaterThan(open.top);
      expect(Math.hypot(place.x - middle.x, place.y - middle.y)).toBeLessThan(60);
    }

    // There, a click on Border Star's light means it: the same panel, the same address and the
    // same camera as the pick.
    await page.mouse.click(Math.round(star.x), Math.round(star.y));
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori', { timeout: 30_000 });
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.closed.today]);
    expect(new URL(page.url()).searchParams.get('school')).toBe('291640000557');
    await expect(input).toHaveValue('Border Star Montessori');
    await expect(panel).toBeFocused();
    // The search index keeps places to 4 decimals (search/format.ts), about 10 m, and the glow
    // the directory's own: the view in the address, and the school on the screen, as near as that.
    const clicked = await landing();
    expect(clicked).toHaveLength(5);
    clicked.forEach((value, i) => {
      expect(Math.abs(value - (picked[i] ?? Number.NaN))).toBeLessThan(i < 3 ? 2e-5 : 1);
    });

    // A click on the map where no school is leaves the panel open.
    await page.mouse.click(1300, 200);
    await page.waitForTimeout(1000);
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    expect(new URL(page.url()).searchParams.get('school')).toBe('291640000557');
    // The click was a step of its own: Back returns to where the zoom toward the two had come.
    await page.goBack();
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
    expect(Number((new URL(page.url()).searchParams.get('at') ?? '').split(',')[2])).toBeCloseTo(
      11,
      1,
    );
    expect(problems).toEqual([]);
    await context.close();
  });
});

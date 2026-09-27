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
 * WebGL here is SwiftShader; nothing below depends on frame rates.
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

import { copy, format } from '../src/copy';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const FIRST_LABEL_LAYER = 'ofm-label-neighbourhood';
const PEMBROKE_HILL = 'A1902690';
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

async function mapView(page: Page): Promise<{ lat: number; lon: number; zoom: number }> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
  });
}

/** Resolves once the map has come to rest near a place. */
async function expectMapNear(page: Page, lat: number, lon: number, zoom: number): Promise<void> {
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
      { timeout: 30_000 },
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
    expect(nextWatch.problems).toEqual([]);
    await later.close();
    await context.close();
  });
});

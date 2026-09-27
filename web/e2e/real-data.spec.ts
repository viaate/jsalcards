/**
 * The site built with the pipeline's real outputs, staged as a deploy stages
 * them (scripts/stage-data.mjs): the school directory, the school tiles, the
 * search index built from the directory and the places build, and whatever
 * live files the pipeline wrote. It is September: there is no closings file,
 * so nothing glows and nothing says what any school is doing.
 *
 * Needs the pipeline's outputs (pipeline/out) and uv; without them, as in CI's
 * e2e job, the spec is skipped. Runs once, under the desktop project.
 * WebGL here is SwiftShader; nothing below depends on frame rates.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { copy } from '../src/copy';
import { BASEMAP_IDS } from '../src/map/basemap/ids';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const PIPELINE_OUT = path.join(WEB, '../pipeline/out');
const SITE_DATA = path.join(PIPELINE_OUT, 'site-data');
const GLOW_LAYER = 'snowlight-glow';
const PEMBROKE_HILL = { id: 'A1902690', lon: -94.593001, lat: 39.03606 };
const PEMBROKE_HILL_NAME = 'The Pembroke Hill School - Wornall Campus';
/** The school tiles' archive, as the build publishes it. */
const SCHOOL_TILES = /\/data\/schools\/schools\.[0-9a-f]{10}\.pmtiles$/;
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

const staged = [
  'schools/meta.json',
  'schools/points.bin',
  'schools/schools.pmtiles',
  'search/cities.jsonl',
  'search/zips.jsonl',
].every((file) => existsSync(path.join(SITE_DATA, file)));

test.skip(!staged, 'needs the pipeline’s outputs in pipeline/out (npm run stage explains)');
test.describe.configure({ mode: 'default', timeout: 120_000 });

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

interface Watch {
  problems: string[];
  requests: { url: string; range: string | null }[];
}

function watch(page: Page): Watch {
  const problems: string[] = [];
  const requests: Watch['requests'] = [];
  page.on('console', (message) => {
    const type = message.type();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(message.text())) {
      problems.push(`console.${type}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
      problems.push(`requestfailed: ${request.url()}`);
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
    }
  });
  page.on('request', (request) =>
    requests.push({ url: request.url(), range: request.headers().range ?? null }),
  );
  return { problems, requests };
}

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
}

const sha256 = (file: string): string =>
  createHash('sha256').update(readFileSync(file)).digest('hex');

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

/** Waits until the map is at rest with every tile in, and one more frame drawn. */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout: 90_000, polling: 250 },
  );
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

/** The schools MapLibre drew in a layer: each one's id and name. */
async function drawn(page: Page, layer: string): Promise<{ id: string; name: string }[]> {
  return page.evaluate((id) => {
    const map = window.snowlightMap;
    if (map?.getLayer(id) === undefined) return [];
    return map.queryRenderedFeatures({ layers: [id] }).map((feature) => ({
      id: String(feature.properties.id),
      name: String(feature.properties.name),
    }));
  }, layer);
}

/** Pembroke Hill's zoom-14 street tile, the deepest OpenFreeMap has: z/x/y. */
const PEMBROKE_HILL_STREET_TILE = '/14/3886/6259.pbf';

/** Whether the map keeps loading the tiles it has zoomed past, as it does during a flight. */
async function keepsTiles(page: Page): Promise<boolean> {
  return page.evaluate(() => window.snowlightMap?.cancelPendingTileRequestsWhileZooming === false);
}

async function mapView(page: Page): Promise<{ lat: number; lon: number; zoom: number }> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
  });
}

let root = '';
let server: PreviewServer | undefined;
let site = '';

test.beforeAll(async () => {
  if (!staged || test.info().project.name !== 'desktop') return;
  test.setTimeout(300_000);
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-real-data-e2e-'));
  const publicDir = path.join(root, 'public');
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  execFileSync(process.execPath, ['scripts/stage-data.mjs', '--to', path.join(publicDir, 'data')], {
    cwd: WEB,
    stdio: 'pipe',
  });
  const outDir = path.join(root, 'site');
  await build({
    root: WEB,
    publicDir,
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

test('the build ships the pipeline’s own files, under names that change with their content', () => {
  const data = path.join(root, 'site', 'data');
  const shipped = filesIn(data).sort();
  const hashed = (plain: string): string => {
    const at = plain.lastIndexOf('.');
    const name = shipped.find((file) =>
      new RegExp(
        `^${plain.slice(0, at)}\\.[0-9a-f]{10}${plain.slice(at).replace('.', '\\.')}$`,
      ).test(file),
    );
    if (name === undefined) throw new Error(`${plain} is not shipped`);
    return name;
  };
  for (const plain of ['schools/meta.json', 'schools/points.bin', 'schools/schools.pmtiles']) {
    const name = hashed(plain);
    const digest = sha256(path.join(data, name));
    expect(digest).toBe(sha256(path.join(SITE_DATA, plain)));
    expect(name).toContain(digest.slice(0, 10));
  }
  const index = hashed('search-index.bin');
  // Everything else the pipeline published, as it wrote it; never its own records or the index inputs.
  const rest = shipped.filter(
    (file) => !/^(schools\/(meta|points|schools)|search-index)\.[0-9a-f]{10}\./.test(file),
  );
  for (const file of rest) {
    expect(sha256(path.join(data, file))).toBe(sha256(path.join(SITE_DATA, file)));
  }
  expect(shipped.filter((file) => /internal|\.jsonl$|^search\//.test(file))).toEqual([]);
  expect(shipped).toHaveLength(rest.length + 4);
  expect(index).toMatch(/^search-index\.[0-9a-f]{10}\.bin$/);
});

test('at the national view nothing under data/ is read, nothing glows and no school says anything', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems, requests } = watch(page);
  await page.goto(site);
  await settle(page);
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
    timeout: 30_000,
  });
  await page.waitForTimeout(1000);
  expect(requests.filter((request) => new URL(request.url).pathname.includes('/data/'))).toEqual(
    [],
  );
  const glow = await page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as
      { implementation: { stats: { count: number; glowCount: number } } } | undefined;
    return layer?.implementation.stats;
  }, GLOW_LAYER);
  expect(glow).toMatchObject({ count: 0, glowCount: 0 });
  // The legend names the statuses as a key; nothing else on the page names one.
  await expect(page.locator('ul.legend li')).toHaveText(Object.values(copy.status));
  const text = await page.evaluate(() => {
    const legend = document.querySelector('ul.legend');
    const key = legend instanceof HTMLElement ? legend.innerText : '';
    return document.body.innerText.replace(key, '');
  });
  for (const status of Object.values(copy.status)) expect(text).not.toContain(status);
  expect(problems).toEqual([]);
  await context.close();
});

test('searching “pembroke” lists Pembroke Hill, and choosing it goes there', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems, requests } = watch(page);
  await page.goto(site);
  await settle(page);
  const indexRequests = (): string[] =>
    requests.map((request) => request.url).filter((url) => url.includes('/data/search-index.'));
  expect(indexRequests()).toEqual([]);

  const input = page.locator('input.search-input');
  await input.click();
  await expect.poll(() => indexRequests().length).toBe(1);
  await input.pressSequentially('pembroke', { delay: 20 });
  const option = page.locator('[role="option"]', { hasText: PEMBROKE_HILL_NAME });
  await expect(option).toHaveCount(1, { timeout: 30_000 });
  await expect(option).toContainText('Kansas City, MO');
  await expect(page.locator('[role="group"]', { has: option })).toHaveAccessibleName(
    copy.search.sections.school,
  );
  await expect(option.locator('b')).toHaveText('Pembroke');
  // The other schools, districts and places named Pembroke are listed with it, from the real index.
  expect(await page.locator('[role="option"]').count()).toBeGreaterThan(5);

  await option.click();
  // The street tiles the flight ends on are asked for as it sets off, long before it gets there,
  // and every tile it asks for on the way keeps loading until the flight is over.
  await expect
    .poll(() => requests.some((request) => request.url.endsWith(PEMBROKE_HILL_STREET_TILE)), {
      timeout: 10_000,
      intervals: [50],
    })
    .toBe(true);
  expect((await mapView(page)).zoom).toBeLessThan(13);
  expect(await keepsTiles(page)).toBe(true);
  await expect(input).toHaveValue(PEMBROKE_HILL_NAME);
  await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);
  await expect
    .poll(
      async () => {
        const view = await mapView(page);
        return (
          Math.abs(view.lat - PEMBROKE_HILL.lat) < 0.001 &&
          Math.abs(view.lon - PEMBROKE_HILL.lon) < 0.001 &&
          Math.abs(view.zoom - 15) < 0.05
        );
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  await settle(page);
  expect(await keepsTiles(page)).toBe(false);
  // Its dot and its name are on the map, read from the school tiles in byte ranges.
  expect(await drawn(page, BASEMAP_IDS.schoolDots)).toContainEqual({
    id: PEMBROKE_HILL.id,
    name: PEMBROKE_HILL_NAME,
  });
  expect(await drawn(page, BASEMAP_IDS.schoolNames)).toContainEqual({
    id: PEMBROKE_HILL.id,
    name: PEMBROKE_HILL_NAME,
  });
  const tiles = requests.filter((request) => SCHOOL_TILES.test(request.url));
  expect(tiles.length).toBeGreaterThan(0);
  expect(tiles.every((request) => request.range?.startsWith('bytes=') === true)).toBe(true);
  expect(indexRequests()).toHaveLength(1);
  expect(problems).toEqual([]);
  await context.close();
});

test('typing “Kansas City” lists the places, then the districts, then the schools, each once', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  await page.goto(site);
  await settle(page);
  const input = page.locator('input.search-input');
  await input.click();
  await input.pressSequentially('Kansas City', { delay: 20 });
  const groups = page.locator('[role="listbox"] > [role="group"]');
  await expect(groups).toHaveCount(3, { timeout: 30_000 });
  for (const [i, kind] of (['city', 'district', 'school'] as const).entries()) {
    await expect(groups.nth(i)).toHaveAccessibleName(copy.search.sections[kind]);
  }
  // The city of Kansas City, Missouri first: the place Enter goes to, shown so.
  const options = page.locator('[role="option"]');
  await expect(options.nth(0)).toHaveText(/^\s*Kansas City\s+Missouri\s*$/);
  await expect(options.nth(1)).toHaveText(/^\s*Kansas City\s+Kansas\s*$/);
  await expect(options.nth(0)).toHaveClass(/is-target/);
  // The districts named for it, then schools named for it; the one school the directory
  // lists twice at one address shows once.
  await expect(groups.nth(1).locator('[role="option"]').first()).toContainText('Kansas City');
  const rows = await options.evaluateAll((all) =>
    all.map((option) => (option instanceof HTMLElement ? option.innerText : '')),
  );
  expect(rows.length).toBeLessThanOrEqual(12);
  expect(new Set(rows).size).toBe(rows.length);
  expect(rows.filter((row) => row.startsWith('Kansas City Academy'))).toHaveLength(1);
  // The list ends inside the screen.
  const box = await page.locator('.results').boundingBox();
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(900);

  await input.press('Enter');
  await expect(input).toHaveValue('Kansas City');
  await expect
    .poll(async () => {
      const view = await mapView(page);
      return Math.abs(view.lat - 39.125155) < 0.001 && Math.abs(view.lon - -94.550313) < 0.001;
    })
    .toBe(true);
  expect(problems).toEqual([]);
  await context.close();
});

test('schools are dots from zoom 11 and named from zoom 13, never one name over another', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems, requests } = watch(page);
  const tileRequests = (): number =>
    requests.filter((request) => SCHOOL_TILES.test(request.url)).length;

  // Kansas City: the metro, the Plaza, Pembroke Hill.
  await page.goto(`${site}?at=39.03,-94.58,10.2`);
  await settle(page);
  expect(await drawn(page, BASEMAP_IDS.schoolDots)).toEqual([]);
  expect(tileRequests()).toBe(0);

  await page.goto(`${site}?at=39.03,-94.58,11.5`);
  await settle(page);
  expect((await drawn(page, BASEMAP_IDS.schoolDots)).length).toBeGreaterThan(100);
  expect(await drawn(page, BASEMAP_IDS.schoolNames)).toEqual([]);

  await page.goto(`${site}?at=39.045,-94.595,13.2`);
  await settle(page);
  const named = await drawn(page, BASEMAP_IDS.schoolNames);
  const dots = await drawn(page, BASEMAP_IDS.schoolDots);
  expect(named.length).toBeGreaterThan(10);
  // Names as the page shows them: none drawn in capitals.
  for (const { name } of named) expect(name).toMatch(/[a-z]/);
  // Where names would collide, fewer are drawn: every school keeps its dot, not every one its name.
  expect(dots.length).toBeGreaterThanOrEqual(named.length);
  // No name, a school's or a street's, is drawn across a school's dot.
  const covered = await page.evaluate(
    ({ dotLayer, space }) => {
      const map = window.snowlightMap;
      if (map === undefined) return ['no map'];
      const labels = map
        .getLayersOrder()
        .filter((id) => map.getLayer(id)?.type === 'symbol' && id !== space);
      return map.queryRenderedFeatures({ layers: [dotLayer] }).flatMap((dot) => {
        const [lon, lat] = (dot.geometry as { coordinates: [number, number] }).coordinates;
        const point = map.project([lon, lat]);
        return map
          .queryRenderedFeatures(point, { layers: labels })
          .map((label) => `${String(label.properties.name)} over ${String(dot.properties.name)}`);
      });
    },
    { dotLayer: BASEMAP_IDS.schoolDots, space: BASEMAP_IDS.schoolSpace },
  );
  expect(covered).toEqual([]);
  const placement = await page.evaluate((layer) => {
    const map = window.snowlightMap;
    const names = ['text-allow-overlap', 'text-ignore-placement', 'text-optional'] as const;
    return names.map((name) => map?.getLayoutProperty(layer, name) as unknown);
  }, BASEMAP_IDS.schoolNames);
  expect(placement).toEqual([false, false, false]);
  // School names are placed first, after the space each dot keeps, so no street or place name
  // takes their room.
  const order = await page.evaluate(() => window.snowlightMap?.getLayersOrder() ?? []);
  expect(order.indexOf(BASEMAP_IDS.schoolSpace)).toBe(order.indexOf(BASEMAP_IDS.schools) - 1);
  expect(order.indexOf(BASEMAP_IDS.schoolNames)).toBe(order.indexOf(BASEMAP_IDS.schools) - 2);
  expect(order.indexOf(BASEMAP_IDS.schoolDots)).toBeLessThan(order.indexOf(GLOW_LAYER));
  expect(problems).toEqual([]);
  await context.close();
});

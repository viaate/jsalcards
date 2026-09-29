/**
 * A pick flies to the school and ends there with its streets drawn, every
 * time, whatever the network does on the way: a US mask or school tiles read
 * back from a compressed copy (as GitHub Pages' CDN serves a file once it or
 * the browser's cache holds its gzip), street tiles that fail a few times,
 * stall, crawl, or cannot be had at all for a while; a browser with no GPU;
 * someone moving the map, or picking another school, mid-flight. Each test
 * checks where the map ends (the school's view: its center and zoom) and that
 * the street tiles there are drawn, as soon as they can arrive, with nobody
 * touching the page.
 *
 * The site is built with the pipeline's real outputs, as real-data.spec.ts
 * builds it, and the street tiles are OpenFreeMap's own, each fetched once
 * for the whole spec and kept (tileNetwork): the failures are made here, the
 * tiles' host is asked nothing twice. Service workers are blocked so every
 * request, the workers' included, passes through the routes. Needs the
 * pipeline's outputs (pipeline/out); without them the spec is skipped. Runs
 * once, under the desktop project, at the owner's window size.
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
  statSync,
  writeFileSync,
} from 'node:fs';
import { createServer as createHttpServer } from 'node:http';
import type { Server } from 'node:http';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import { chromium, expect, test } from '@playwright/test';
import type { Browser, BrowserContext, Page, Route } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { BASEMAP_IDS } from '../src/map/basemap/ids';
import { US_MASK_FILE } from '../src/map/basemap/us-mask';
import { formatView } from '../src/state/url';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const SITE_DATA = path.join(WEB, '../pipeline/out/site-data');
/** The owner's window. */
const VIEWPORT = { width: 1569, height: 959 };
const SCHOOL_TILES = /\/data\/schools\/schools\.[0-9a-f]{10}\.pmtiles$/;
const US_MASK = /\/geo\/us-mask\.[0-9a-f]+\.pmtiles$/;

interface School {
  readonly id: string;
  readonly query: string;
  readonly name: RegExp;
  /** Where a pick of it ends in the owner's window: framed beside its panel, at street zoom. */
  readonly view: readonly [lat: number, lon: number, zoom: number];
}
const PEMBROKE_HILL: School = {
  id: 'A1902690',
  query: 'The Pembroke Hill School - Wornall Campus',
  name: /Pembroke Hill School - Wornall Campus/,
  view: [39.03663, -94.59716, 15],
};
const SHAWNEE_MISSION_EAST: School = {
  id: '201164001574',
  query: 'Shawnee Mission East',
  name: /Shawnee Mission East High/,
  view: [38.99222, -94.63616, 15],
};

const staged = [
  'schools/meta.json',
  'schools/points.bin',
  'schools/schools.pmtiles',
  'search/cities.jsonl',
  'search/zips.jsonl',
].every((file) => existsSync(path.join(SITE_DATA, file)));

test.skip(!staged, 'needs the pipeline’s outputs in pipeline/out (npm run stage explains)');
test.describe.configure({ mode: 'default', timeout: 180_000 });

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewport; runs once.');
});

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
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

let root = '';
let outDir = '';
let server: PreviewServer | undefined;
let site = '';

test.beforeAll(async () => {
  if (!staged || test.info().project.name !== 'desktop') return;
  test.setTimeout(300_000);
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-flight-e2e-'));
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
  outDir = path.join(root, 'site');
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

/**
 * The built site served as GitHub Pages serves it: every file cacheable for
 * ten minutes, varying by Accept-Encoding, with an ETag; gzipped for a
 * browser that accepts gzip, and a Range applied to the bytes sent, the gzip
 * when there is one. Only a browser cache sits between it and the page.
 */
async function pagesServer(): Promise<{ url: string; server: Server }> {
  const types: Readonly<Record<string, string>> = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
  };
  const zipped = new Set(['.html', '.js', '.css', '.json', '.svg', '.pmtiles', '.bin']);
  const kept = new Map<string, { raw: Buffer; gzip: Buffer | null; etag: string }>();
  const http = createHttpServer((request, response) => {
    let file = path.join(outDir, decodeURIComponent(new URL(request.url ?? '/', site).pathname));
    if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!file.startsWith(outDir) || !existsSync(file)) {
      response.writeHead(404).end();
      return;
    }
    const ext = path.extname(file);
    let entry = kept.get(file);
    if (entry === undefined) {
      const raw = readFileSync(file);
      entry = {
        raw,
        gzip: zipped.has(ext) ? gzipSync(raw) : null,
        etag: `"${createHash('sha1').update(raw).digest('hex').slice(0, 16)}"`,
      };
      kept.set(file, entry);
    }
    const gzip = /\bgzip\b/.test(request.headers['accept-encoding'] ?? '') ? entry.gzip : null;
    const body = gzip ?? entry.raw;
    const headers: Record<string, string> = {
      'content-type': types[ext] ?? 'application/octet-stream',
      'cache-control': 'max-age=600',
      vary: 'Accept-Encoding',
      etag: entry.etag,
      'accept-ranges': 'bytes',
      ...(gzip === null ? {} : { 'content-encoding': 'gzip' }),
    };
    if (request.headers['if-none-match'] === entry.etag) {
      response.writeHead(304, headers).end();
      return;
    }
    const range = /^bytes=(\d+)-(\d*)$/.exec(request.headers.range ?? '');
    if (range === null) {
      response.writeHead(200, headers).end(body);
      return;
    }
    const first = Number(range[1]);
    const last = Math.min(range[2] === '' ? body.length - 1 : Number(range[2]), body.length - 1);
    response
      .writeHead(206, {
        ...headers,
        'content-range': `bytes ${String(first)}-${String(last)}/${String(body.length)}`,
      })
      .end(body.subarray(first, last + 1));
  });
  const port = await freePort();
  await new Promise<void>((resolve) => http.listen(port, '127.0.0.1', resolve));
  return { url: `http://127.0.0.1:${String(port)}/`, server: http };
}

/** An answer from OpenFreeMap. */
interface Answer {
  readonly status: number;
  readonly headers: Record<string, string>;
  readonly body: Buffer;
}

/** OpenFreeMap's answers, each fetched once for the whole spec. */
const fetched = new Map<string, Promise<Answer>>();

/** OpenFreeMap's own answer to a request, fetched once for the whole spec and kept. */
function upstream(route: Route, url: string): Promise<Answer> {
  let answer = fetched.get(url);
  if (answer === undefined) {
    answer = route.fetch().then(async (response) => ({
      status: response.status(),
      headers: response.headers(),
      body: await response.body(),
    }));
    fetched.set(url, answer);
    answer.catch(() => fetched.delete(url));
  }
  return answer;
}

/** What happens to a request to OpenFreeMap: answered as it is, or failed some way first. */
type Fault = (route: Route, url: string, attempt: number) => Promise<boolean>;

interface TileNetwork {
  /** Requests to OpenFreeMap so far, by URL. */
  readonly attempts: Map<string, number>;
  /** Whether a request is turned away (the host blocked); true until said otherwise. */
  blocked: boolean;
}

/**
 * Serves OpenFreeMap through `fault`, which may fail a request (and say so),
 * or let it through to OpenFreeMap's own answer, fetched once and kept.
 */
async function tileNetwork(context: BrowserContext, fault?: Fault): Promise<TileNetwork> {
  const network: TileNetwork = { attempts: new Map(), blocked: false };
  await context.route(/^https:\/\/tiles\.openfreemap\.org\//, async (route) => {
    const url = route.request().url();
    const attempt = (network.attempts.get(url) ?? 0) + 1;
    network.attempts.set(url, attempt);
    if (network.blocked) {
      await route.abort('connectionrefused');
      return;
    }
    if (fault !== undefined && (await fault(route, url, attempt))) return;
    try {
      const { status, headers, body } = await upstream(route, url);
      // The body as the browser reads it: unzipped already.
      const kept = Object.fromEntries(
        Object.entries(headers).filter(
          ([name]) => name !== 'content-encoding' && name !== 'content-length',
        ),
      );
      await route.fulfill({ status, headers: kept, body });
    } catch {
      await route.abort('failed');
    }
  });
  return network;
}

const isTile = (url: string): boolean => /\/\d+\/\d+\/\d+\.pbf$/.test(url);

/**
 * What a page logs as an error that is no fault of it: the browser's own line
 * for each request the network here fails on purpose, and the GPU driver's.
 */
const EXPECTED_ERRORS = /^Failed to load resource|GL Driver Message|GPU stall due to ReadPixels/;

/**
 * A new page at the owner's window size, service workers blocked so the
 * routes see every request; `errors` gathers what it throws or logs as an
 * error (a tile that fails is only warned of, once).
 */
async function newPage(
  browser: Browser,
): Promise<{ context: BrowserContext; page: Page; errors: string[] }> {
  const context = await browser.newContext({ viewport: VIEWPORT, serviceWorkers: 'block' });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !EXPECTED_ERRORS.test(message.text())) {
      errors.push(`console.error: ${message.text()}`);
    }
  });
  return { context, page, errors };
}

/** Opens the site at the national view, the map up. */
async function open(page: Page, url = site): Promise<void> {
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  await page.waitForFunction(() => window.snowlightMap?.loaded() === true, null, {
    timeout: 60_000,
  });
}

/** Searches for a school and picks it, as someone would. */
async function pick(page: Page, school: School): Promise<void> {
  const input = page.locator('input.search-input');
  await input.click();
  await input.fill('');
  await input.pressSequentially(school.query, { delay: 10 });
  await page
    .locator('[role="option"]', { hasText: school.name })
    .first()
    .click({ timeout: 30_000 });
}

/** Where the map is, where the address says it is going, and what it has drawn there. */
interface MapState {
  readonly zoom: number;
  readonly lat: number;
  readonly lon: number;
  /** The view the address names: where a flight is going, or where the map is. */
  readonly at: readonly [lat: number, lon: number, zoom: number] | null;
  /** The same, as the address writes it (fewer decimals further out). */
  readonly atText: string | null;
  readonly school: string | null;
  /** A flight is on its way (the map keeps every tile it asks for loading). */
  readonly flying: boolean;
  readonly moving: boolean;
  /** Street tiles cover the screen at the map's own zoom, all of them in, and roads are drawn. */
  readonly streets: boolean;
  readonly roads: number;
  /** The zooms of the street tiles drawn, coarsest first. */
  readonly tileZooms: readonly number[];
}

async function mapState(page: Page): Promise<MapState> {
  return page.evaluate(
    ({ streets, roadLayer }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const center = map.getCenter();
      const zoom = map.getZoom();
      const tiles = map.style.tileManagers[streets];
      const ids = tiles?.getRenderableIds() ?? [];
      const drawn = ids.flatMap((id) => {
        const tile = tiles?.getTileByID(id);
        return tile === undefined
          ? []
          : [{ z: tile.tileID.overscaledZ, loaded: tile.state === 'loaded' }];
      });
      const roads =
        map.getLayer(roadLayer) === undefined
          ? 0
          : map.queryRenderedFeatures({ layers: [roadLayer] }).length;
      const params = new URL(location.href).searchParams;
      const atText = params.get('at');
      const at = atText?.split(',').map(Number) ?? null;
      const ideal = Math.floor(zoom + 1e-6);
      return {
        zoom,
        lat: center.lat,
        lon: center.lng,
        at: at?.length === 3 ? (at as [number, number, number]) : null,
        atText,
        school: params.get('school'),
        flying: !map.cancelPendingTileRequestsWhileZooming,
        moving: map.isMoving(),
        streets:
          drawn.length > 0 && drawn.every((tile) => tile.loaded && tile.z >= ideal) && roads > 0,
        roads,
        tileZooms: drawn.map((tile) => tile.z).sort((a, b) => a - b),
      };
    },
    { streets: BASEMAP_IDS.openFreeMapSource, roadLayer: BASEMAP_IDS.ofmRoad },
  );
}

/**
 * Whether the map is at rest at the view the address names, as the address
 * writes the view the map is at, and the flight over.
 */
function arrived(state: MapState): boolean {
  return (
    state.atText !== null &&
    !state.flying &&
    !state.moving &&
    formatView({ lat: state.lat, lon: state.lon, zoom: state.zoom }) === state.atText
  );
}

/** Whether the map is at `school`'s view: its center, and its zoom. */
function atSchool(state: MapState, school: School): boolean {
  const [lat, lon, zoom] = school.view;
  return (
    state.school === school.id &&
    Math.abs(state.lat - lat) < 1e-4 &&
    Math.abs(state.lon - lon) < 1e-4 &&
    Math.abs(state.zoom - zoom) < 0.01
  );
}

/**
 * Waits for the map to end at `school`'s view, at rest, the flight over, with
 * (unless told not to) its streets drawn; fails with the last state seen.
 */
async function expectAtSchool(
  page: Page,
  school: School,
  { streets = true, timeout = 90_000 }: { streets?: boolean; timeout?: number } = {},
): Promise<MapState> {
  let last: MapState | null = null;
  await expect
    .poll(
      async () => {
        last = await mapState(page);
        return arrived(last) && atSchool(last, school) && (!streets || last.streets);
      },
      { timeout, intervals: [250], message: `at ${school.id}${streets ? ' with streets' : ''}` },
    )
    .toBe(true)
    .catch((error: unknown) => {
      throw new Error(`${String(error)}\nlast: ${JSON.stringify(last)}`);
    });
  const state = last as unknown as MapState;
  // The school's own view: its center and zoom, the address naming it.
  expect(state.lat).toBeCloseTo(school.view[0], 4);
  expect(state.lon).toBeCloseTo(school.view[1], 4);
  expect(state.zoom).toBeCloseTo(school.view[2], 2);
  if (streets) {
    expect(state.roads).toBeGreaterThan(0);
    expect(Math.min(...state.tileZooms)).toBeGreaterThanOrEqual(Math.floor(school.view[2]) - 1);
  }
  return state;
}

/** Whether the school's dot is drawn on the map. */
async function dotDrawn(page: Page, school: School): Promise<boolean> {
  return page.evaluate(
    ({ layer, id }) =>
      window.snowlightMap
        ?.queryRenderedFeatures({ layers: [layer] })
        .some((feature) => String(feature.properties.id) === id) ?? false,
    { layer: BASEMAP_IDS.schoolDots, id: school.id },
  );
}

/** A range of `bytes` as GitHub Pages' CDN answers it from its gzip: those bytes of the gzip. */
async function fulfillFromGzip(route: Route, zipped: Buffer, range: string): Promise<void> {
  const [, from = '0', to = '0'] = /bytes=(\d+)-(\d+)/.exec(range) ?? [];
  const last = Math.min(Number(to), zipped.length - 1);
  await route.fulfill({
    status: 206,
    headers: {
      'content-type': 'application/octet-stream',
      'content-encoding': 'gzip',
      'content-range': `bytes ${from}-${String(last)}/${String(zipped.length)}`,
    },
    body: zipped.subarray(Number(from), last + 1),
  });
}

test('the US mask served as GitHub Pages’ CDN serves it once it holds its gzip: the flight ends at the school, streets drawn', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  await tileNetwork(context);
  const zipped = gzipSync(readFileSync(path.join(WEB, 'public', US_MASK_FILE)));
  const asked = { whole: 0, ranges: 0 };
  // The whole file comes as its gzip, and a range of it as that range of the gzip, both marked gzip.
  // (A routed answer reaches the page as it is sent: nothing unzips either.)
  await context.route(US_MASK, async (route) => {
    const range = route.request().headers().range;
    if (range === undefined) {
      asked.whole++;
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/octet-stream', 'content-encoding': 'gzip' },
        body: zipped,
      });
      return;
    }
    asked.ranges++;
    await fulfillFromGzip(route, zipped, range);
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expectAtSchool(page, PEMBROKE_HILL);
  // Read whole, never in ranges: nothing a server or cache holds of it can come back wrong.
  expect(asked.ranges).toBe(0);
  expect(asked.whole).toBeGreaterThan(0);
  expect(errors).toEqual([]);
  await context.close();
});

test('the US mask in the browser’s own cache as a gzip, as the owner’s browser held it: the flight ends at the school, streets drawn', async ({
  browser,
}) => {
  // No routes here: a route turns the browser's cache off, and this is about what the cache holds.
  // The site as GitHub Pages serves it, and OpenFreeMap itself.
  const pages = await pagesServer();
  try {
    const { context, page, errors } = await newPage(browser);
    await open(page, pages.url);
    // The whole mask, gzipped, now in the browser's cache, as the owner's was: the ranges the map
    // read of it came back as ranges of that gzip, for as long as the copy lived.
    const cached = await page.evaluate(async (file) => {
      const response = await fetch(file);
      return (await response.arrayBuffer()).byteLength;
    }, US_MASK_FILE);
    expect(cached).toBe(statSync(path.join(WEB, 'public', US_MASK_FILE)).size);
    await pick(page, PEMBROKE_HILL);
    await expectAtSchool(page, PEMBROKE_HILL);
    expect(errors).toEqual([]);
    await context.close();
  } finally {
    await new Promise((resolve) => pages.server.close(resolve));
  }
});

test('school tiles read back wrong, then right: the school’s dot is drawn once they are, untouched', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  await tileNetwork(context);
  const zipped = gzipSync(readFileSync(path.join(SITE_DATA, 'schools/schools.pmtiles')));
  let wrong = true;
  let wrongAnswers = 0;
  // Every range comes back as GitHub Pages' CDN answers once it holds the file gzipped, until the
  // map is at the school: then as it should.
  await context.route(SCHOOL_TILES, async (route) => {
    const range = route.request().headers().range;
    if (range === undefined || !wrong) {
      await route.fallback();
      return;
    }
    wrongAnswers++;
    await fulfillFromGzip(route, zipped, range);
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expectAtSchool(page, PEMBROKE_HILL);
  expect(wrongAnswers).toBeGreaterThan(0);
  expect(await dotDrawn(page, PEMBROKE_HILL)).toBe(false);
  wrong = false;
  // Nobody moves the map: the school tiles that failed are asked for again, and come.
  await expect.poll(() => dotDrawn(page, PEMBROKE_HILL), { timeout: 90_000 }).toBe(true);
  await expectAtSchool(page, PEMBROKE_HILL);
  expect(errors).toEqual([]);
  await context.close();
});

test('the tile host out of reach for a while: the flight ends at the school, and its streets come once it is back, untouched', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  const network = await tileNetwork(context);
  await open(page);
  network.blocked = true;
  await pick(page, PEMBROKE_HILL);
  // At the school, at street zoom, without its streets: none can be had.
  const there = await expectAtSchool(page, PEMBROKE_HILL, { streets: false, timeout: 60_000 });
  expect(there.streets).toBe(false);
  // The page keeps asking, without anyone touching it; the moment the host answers, the streets come.
  const asked = (): number => [...network.attempts.values()].reduce((sum, n) => sum + n, 0);
  const before = asked();
  await expect.poll(asked, { timeout: 40_000 }).toBeGreaterThan(before);
  network.blocked = false;
  await expectAtSchool(page, PEMBROKE_HILL, { timeout: 60_000 });
  expect(errors).toEqual([]);
  await context.close();
});

test('a slow network whose proxy cuts what it cannot answer in time: the flight ends at the school, streets drawn', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  // A school's slow link, shared: one tile at a time at 200 KB a second, behind a proxy that answers
  // a 504 to any request it cannot answer within 8 seconds of it being made. Queued behind others, a
  // request is cut; the link then goes on to the next.
  const RATE = 200_000;
  const BUDGET_MS = 8000;
  let linkFree = 0;
  let cut = 0;
  await tileNetwork(context, async (route, url) => {
    if (!isTile(url)) return false;
    const { body } = await upstream(route, url);
    const asked = Date.now();
    const done = Math.max(linkFree, asked) + (body.length / RATE) * 1000;
    if (done - asked > BUDGET_MS) {
      cut++;
      await new Promise((resolve) => setTimeout(resolve, BUDGET_MS));
      await route.fulfill({
        status: 504,
        contentType: 'text/html',
        body: '<!doctype html><title>Gateway Timeout</title>',
      });
      return true;
    }
    linkFree = done;
    await new Promise((resolve) => setTimeout(resolve, done - asked));
    return false;
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expectAtSchool(page, PEMBROKE_HILL, { timeout: 150_000 });
  expect(cut).toBeGreaterThan(0);
  expect(errors).toEqual([]);
  await context.close();
});

test('a second pick mid-flight: the map ends at the second school, streets drawn', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  // The first two requests for each tile (the page's ahead of the flight, and the map's) fail, as on
  // a network that drops some.
  await tileNetwork(context, async (route, url, attempt) => {
    if (!isTile(url) || attempt > 2) return false;
    await route.abort('connectionreset');
    return true;
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expect
    .poll(async () => (await mapState(page)).zoom, { timeout: 30_000 })
    .toBeGreaterThan(5);
  await pick(page, SHAWNEE_MISSION_EAST);
  await expectAtSchool(page, SHAWNEE_MISSION_EAST);
  expect(errors).toEqual([]);
  await context.close();
});

test('street tiles failing again and again before they answer: the flight still ends at the school, streets drawn', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  // Each tile fails four times, a different way each time, then answers.
  const network = await tileNetwork(context, async (route, url, attempt) => {
    if (!isTile(url) || attempt > 4) return false;
    if (attempt === 1) await route.fulfill({ status: 503, body: 'busy' });
    else if (attempt === 2) await route.abort('connectionreset');
    else if (attempt === 3) {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        headers: { 'access-control-allow-origin': '*' },
        body: '<!doctype html><title>Blocked by your network</title>',
      });
    } else await route.fulfill({ status: 429, headers: { 'retry-after': '1' }, body: 'slow down' });
    return true;
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expectAtSchool(page, PEMBROKE_HILL);
  expect(
    [...network.attempts.entries()].filter(([url, n]) => isTile(url) && n > 4).length,
  ).toBeGreaterThan(0);
  expect(errors).toEqual([]);
  await context.close();
});

test('street tiles that never answer at first: the flight still ends at the school, streets drawn', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  // The first two requests for each tile (the page's, ahead of the flight, and a worker's) are held
  // without an answer, as a stalled connection holds them.
  await tileNetwork(context, async (_route, url, attempt) => {
    if (!isTile(url) || attempt > 2) return false;
    await new Promise(() => undefined);
    return true;
  });
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expectAtSchool(page, PEMBROKE_HILL, { timeout: 120_000 });
  expect(errors).toEqual([]);
  await context.close();
});

test('with no GPU, drawn in software: the flight ends at the school, streets drawn', async () => {
  const software = await chromium.launch({
    args: ['--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  try {
    const { context, page, errors } = await newPage(software);
    await tileNetwork(context);
    await open(page);
    await pick(page, PEMBROKE_HILL);
    await expectAtSchool(page, PEMBROKE_HILL, { timeout: 150_000 });
    expect(errors).toEqual([]);
    await context.close();
  } finally {
    await software.close();
  }
});

test('someone scrolling mid-flight has the map, at rest where they left it; a pick after goes to the school', async ({
  browser,
}) => {
  const { context, page, errors } = await newPage(browser);
  await tileNetwork(context);
  await open(page);
  await pick(page, PEMBROKE_HILL);
  await expect
    .poll(async () => (await mapState(page)).zoom, { timeout: 30_000 })
    .toBeGreaterThan(5);
  await page.mouse.move(1150, 500);
  await page.mouse.wheel(0, -300);
  // Theirs: no flight left on its way, at rest, the address where the map is, streets drawn there.
  await expect
    .poll(
      async () => {
        const state = await mapState(page);
        return arrived(state) && (state.zoom < 7.5 || state.streets);
      },
      { timeout: 60_000, intervals: [250] },
    )
    .toBe(true);
  const left = await mapState(page);
  await page.waitForTimeout(2000);
  const later = await mapState(page);
  expect([later.lat, later.lon, later.zoom]).toEqual([left.lat, left.lon, left.zoom]);
  await pick(page, SHAWNEE_MISSION_EAST);
  await expectAtSchool(page, SHAWNEE_MISSION_EAST);
  expect(errors).toEqual([]);
  await context.close();
});

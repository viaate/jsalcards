/**
 * Replay mode: a past storm day on the map in live's place (src/app/replay.ts).
 *
 * The spec stages a build of its own in a temporary folder and serves it
 * with a small server of its own, the service worker on. Every data file in
 * it is SYNTHETIC, made up here and nowhere else: a directory of
 * eight made-up schools near Kansas City, their records and one ZIP code's
 * area; a live file (set A, two schools closed today) and replay days (set
 * B, four other schools on Mon, Jan 5, 2026), disjoint so the map's count
 * tells which is lit. The page's calendar is fixed on Wed, Jan 7, 2026, at
 * 8 AM in Kansas City.
 *
 * The first build also ships days the page must refuse: today's, a future
 * one, and one stamped for another directory. A deploy before it, which
 * stamped the day for an older directory, is played by copies put in the
 * worker's caches as that deploy would have left them.
 *
 * Runs once, under the desktop project; tests set their own viewports.
 * WebGL here is SwiftShader, whose frames are slow; waits are generous.
 */
import { createHash } from 'node:crypto';
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { createServer } from 'node:http';
import type { Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { devices, expect, test } from '@playwright/test';
import type { Browser, BrowserContext, BrowserContextOptions, Page } from '@playwright/test';
import { build } from 'vite';

import { copy } from '../src/copy';
import { format } from '../src/copy-format';
import { hashedPath } from '../src/data/paths';
import { CACHE_NAMES } from '../src/pwa/config';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
/** Playwright's own line when a test blocks the service worker, not the page's. */
const BLOCKED_WORKER = 'Service Worker registration blocked by Playwright';
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

test.describe.configure({ mode: 'default', timeout: 180_000 });

// Synthetic data, for these tests only. -----------------------------------------------

const DAY = '2026-01-05';
const DAY_TEXT = 'Mon, Jan 5, 2026';
/** 8 AM in Kansas City on Wed, Jan 7, 2026. */
const NOW = new Date('2026-01-07T14:00:00Z');
const LIVE_AT = '2026-01-07T13:45:00Z';
const DISTRICT = ['2999999', 'TEST VALLEY R-1'] as const;
const ZONE = 'America/Chicago';

/** Eight made-up schools near Kansas City, in the directory's order. */
const SCHOOLS = [
  ['290000000001', 'Alder Elementary', -94.62, 39.03],
  ['290000000002', 'Birch Elementary', -94.6, 39.05],
  ['290000000003', 'Cedar Elementary', -94.58, 39.02],
  ['290000000004', 'Dogwood Middle', -94.57, 39.04],
  ['290000000005', 'Elm High', -94.61, 39.01],
  ['290000000006', 'Fir Elementary', -94.59, 39.06],
  ['290000000007', 'Ginkgo Elementary', -94.3, 38.8],
  ['290000000008', 'Hazel Academy', -94.9, 39.3],
] as const;

/** Live, today (set A): the first two closed. */
const LIVE_ROWS: readonly (readonly [number, number])[] = [
  [0, 0],
  [1, 0],
];
/** The replay day (set B): two closed, one delayed, one remote, for a winter storm. */
const REPLAY_ROWS: readonly (readonly [number, number])[] = [
  [2, 0],
  [3, 0],
  [4, 2],
  [5, 1],
];
/** The deploy before's copy of the day, stamped for its own directory: three schools. */
const REPLAY_ROWS_OLD: readonly (readonly [number, number])[] = [
  [2, 0],
  [3, 0],
  [4, 2],
];

interface Stamp {
  generated_on: string;
  schools: number;
  districts: number;
}
const STAMP_1: Stamp = { generated_on: '2026-01-03', schools: SCHOOLS.length, districts: 1 };

function meta(stamp: Stamp): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: stamp.generated_on,
    count: SCHOOLS.length,
    ids: SCHOOLS.map(([id]) => id),
    names: SCHOOLS.map(([, name]) => name),
    districts: { ids: [DISTRICT[0]], names: [DISTRICT[1]] },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

function points(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * SCHOOLS.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(SCHOOLS.length, 8);
  bytes.writeUInt32LE(1, 12);
  SCHOOLS.forEach(([, , lon, lat], i) => {
    const at = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(lon * 1e6), at);
    bytes.writeInt32LE(Math.round(lat * 1e6), at + 4);
    bytes.writeUInt32LE(0, at + 8);
    bytes.writeUInt8(0, at + 12);
  });
  return bytes;
}

/** Each school's record; Cedar's nearest are Elm (remote on the day) and Alder (closed today). */
function details(stamp: Stamp): { index: string; shard: string } {
  const rows = SCHOOLS.map(([id, name], i) => [
    id,
    name,
    0,
    0,
    DISTRICT[0],
    DISTRICT[1],
    `${String(100 + i)} MAIN ST`,
    'KANSAS CITY',
    'MO',
    '64112',
    'Jackson County',
    'KG',
    '05',
    300 + i,
    '8165550100',
    i === 2
      ? [
          [4, SCHOOLS[4][0], SCHOOLS[4][1], 900, SCHOOLS[4][2], SCHOOLS[4][3]],
          [0, SCHOOLS[0][0], SCHOOLS[0][1], 1200, SCHOOLS[0][2], SCHOOLS[0][3]],
        ]
      : [],
  ]);
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory: stamp,
      shards: 1,
      first_ids: [SCHOOLS[0][0]],
      files: ['0.json'],
    }),
    shard: JSON.stringify({ schema_version: 1, directory: stamp, first: 0, rows }),
  };
}

/** ZIP code 64112's area: the first six schools. */
function areas(stamp: Stamp): { index: string; shard: string } {
  const own = SCHOOLS.slice(0, 6).map(([id, , lon, lat], i) => [i, id, 300 + i * 200, lon, lat]);
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory: stamp,
      shards: 1,
      first_zips: ['64112'],
      files: ['0.json'],
    }),
    shard: JSON.stringify({
      schema_version: 1,
      directory: stamp,
      first: '64112',
      areas: [['64112', -94.595, 39.036, ['MO'], own, []]],
    }),
  };
}

function closings(stamp: Stamp): string {
  let before = -1;
  return JSON.stringify({
    schema_version: 1,
    generated_at: LIVE_AT,
    directory: stamp,
    days: [
      {
        day: '2026-01-07',
        gaps: LIVE_ROWS.map(([school]) => {
          const gap = school - before - 1;
          before = school;
          return gap;
        }),
        statuses: LIVE_ROWS.map(([, status]) => status),
        announced: LIVE_ROWS.map(() => 60),
        reasons: LIVE_ROWS.map(() => 0),
        shifts: [],
        clocks: [],
      },
    ],
  });
}

function replay(day: string, stamp: Stamp, rows: readonly (readonly [number, number])[]): string {
  return JSON.stringify({
    schema_version: 1,
    id: day,
    generated_at: '2026-01-06T12:00:00Z',
    directory: stamp,
    start: `${day}T12:00:00Z`,
    step_minutes: 1440,
    frames: 1,
    rows: rows.map(([school, status]) => [school, status, 0, 0, 0]),
  });
}

function replayIndex(days: readonly { id: string; schools: number }[]): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-06T12:00:00Z',
    replays: days.map(({ id, schools }) => ({
      id,
      start: `${id}T12:00:00Z`,
      step_minutes: 1440,
      frames: 1,
      peak_schools: schools,
      peak_frame: 0,
      schools,
      states: ['MO'],
    })),
  });
}

// Builds, served as one site. -------------------------------------------------------

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
    )
    .sort();
}

const sha256 = (text: string | Buffer): string => createHash('sha256').update(text).digest('hex');

/** Builds the site with these files staged in data/, each replay day hashed as staging names it. */
async function stageBuild(
  root: string,
  name: string,
  stamp: Stamp,
  replays: Record<string, string>,
  index: string,
): Promise<{ dir: string; replayNames: Record<string, string> }> {
  const publicDir = path.join(root, `${name}-public`);
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  const data = path.join(publicDir, 'data');
  const put = (file: string, bytes: string | Buffer): void => {
    mkdirSync(path.dirname(path.join(data, file)), { recursive: true });
    writeFileSync(path.join(data, file), bytes);
  };
  put('schools/meta.json', meta(stamp));
  put('schools/points.bin', points());
  const detail = details(stamp);
  put('schools/details/index.json', detail.index);
  put('schools/details/0.json', detail.shard);
  const area = areas(stamp);
  put('schools/areas/index.json', area.index);
  put('schools/areas/0.json', area.shard);
  put('live/closings.json', closings(stamp));
  put('replays/index.json', index);
  const replayNames: Record<string, string> = {};
  for (const [day, text] of Object.entries(replays)) {
    const published = hashedPath(`replays/${day}.json`, sha256(text));
    replayNames[day] = published;
    put(published, text);
  }
  const dir = path.join(root, name);
  await build({
    root: WEB,
    publicDir,
    cacheDir: path.join(root, `${name}-vite-cache`),
    logLevel: 'warn',
    build: { outDir: dir, emptyOutDir: true },
  });
  return { dir, replayNames };
}

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.bin': 'application/octet-stream',
  '.pmtiles': 'application/octet-stream',
  '.txt': 'text/plain',
};

/** One origin serving the build. */
interface Site {
  url: string;
  stop(): Promise<void>;
}

async function serve(dir: string): Promise<Site> {
  const current = dir;
  const server: Server = createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url ?? '/', 'http://x').pathname);
    let file = path.join(current, pathname);
    if (!file.startsWith(current)) {
      response.writeHead(403).end();
      return;
    }
    try {
      if (statSync(file).isDirectory()) file = path.join(file, 'index.html');
      const body = readFileSync(file);
      response.writeHead(200, {
        'Content-Type': TYPES[path.extname(file)] ?? 'application/octet-stream',
        'Cache-Control': 'no-cache',
      });
      response.end(body);
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${String(port)}/`,
    stop: () =>
      new Promise<void>((resolve) => {
        server.close(() => {
          resolve();
        });
      }),
  };
}

// The page. -------------------------------------------------------------------------

/** Stops the page's calendar at `now`, and nothing else (as app.spec.ts fixDate). */
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

interface Visit {
  page: Page;
  context: BrowserContext;
  problems: string[];
  requests: string[];
}

async function visit(
  browser: Browser,
  url: string,
  options: BrowserContextOptions = { viewport: { width: 1280, height: 800 } },
  context?: BrowserContext,
): Promise<Visit> {
  const own =
    context ??
    (await browser.newContext({ serviceWorkers: 'block', timezoneId: ZONE, ...options }));
  const page = await own.newPage();
  const problems: string[] = [];
  const requests: string[] = [];
  page.on('console', (message) => {
    const text = message.text();
    if (
      (message.type() === 'error' || message.type() === 'warning') &&
      !GPU_DRIVER_NOISE.test(text) &&
      text !== BLOCKED_WORKER
    )
      problems.push(`console.${message.type()}: ${text}`);
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('request', (request) => requests.push(request.url()));
  await fixDate(page, NOW);
  // Every paint of the glow, by how many schools it lit, from the first frame on.
  await page.addInitScript((layerId: string) => {
    const counts: number[] = [];
    (window as unknown as { __paints: number[] }).__paints = counts;
    const look = (): void => {
      const layer = (
        window as unknown as {
          snowlightMap?: {
            getLayer(id: string): { implementation?: { stats?: { count: number } } };
          };
        }
      ).snowlightMap?.getLayer(layerId);
      const count = layer?.implementation?.stats?.count;
      if (count !== undefined && counts.at(-1) !== count) counts.push(count);
      requestAnimationFrame(look);
    };
    requestAnimationFrame(look);
  }, GLOW_LAYER);
  await page.goto(url);
  return { page, context: own, problems, requests };
}

async function litCount(page: Page): Promise<number> {
  return page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as
      { implementation: { stats: { count: number } } } | undefined;
    return layer?.implementation.stats.count ?? -1;
  }, GLOW_LAYER);
}

async function waitForLit(page: Page, count: number): Promise<void> {
  await expect.poll(() => litCount(page), { timeout: 60_000 }).toBe(count);
}

/** The key's counts at the foot of the screen, in status order ('' for none). */
async function legend(page: Page): Promise<string[]> {
  return page
    .locator('ul.legend li')
    .evaluateAll((items) => items.map((item) => item.querySelector('.count')?.textContent ?? ''));
}

async function openReplayPage(page: Page): Promise<void> {
  await page.locator('.menu-button').click();
  await page.locator('aside.menu [data-page="replay"]').click();
}

async function enterFromMenu(page: Page, label = DAY_TEXT): Promise<void> {
  await openReplayPage(page);
  await page.locator('aside.menu .day', { hasText: label }).click();
}

/** Every layout shift the page has had: none is ever expected. */
async function layoutShifts(page: Page): Promise<number[]> {
  return page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const observer = new PerformanceObserver((list) => {
          observer.disconnect();
          resolve(list.getEntries().map((entry) => (entry as unknown as { value: number }).value));
        });
        observer.observe({ type: 'layout-shift', buffered: true });
        setTimeout(() => {
          observer.disconnect();
          resolve([]);
        }, 500);
      }),
  );
}

const BAR = '.updated.replay';
const LIVE_LINE = /^\s*Live · 7:45\sAM$/u;
const TODAY_WORDS =
  /\bLive\b|Updated|\btoday\b|\btomorrow\b|\bOpen\b|Offline|No weather closures|Posted/u;

// The tests. ------------------------------------------------------------------------

let root = '';
let site: Site | undefined;
let first: Awaited<ReturnType<typeof stageBuild>> | undefined;

test.beforeAll(async () => {
  test.setTimeout(400_000);
  if (test.info().project.name !== 'desktop') return;
  root = mkdtempSync(path.join(tmpdir(), 'snowlight-replay-e2e-'));
  first = await stageBuild(
    root,
    'build-1',
    STAMP_1,
    {
      [DAY]: replay(DAY, STAMP_1, REPLAY_ROWS),
      // Today, and a day still to come: shipped by mistake, never shown.
      '2026-01-07': replay('2026-01-07', STAMP_1, REPLAY_ROWS),
      '2026-01-09': replay('2026-01-09', STAMP_1, REPLAY_ROWS),
      // Stamped for another directory: never lights.
      '2026-01-02': replay('2026-01-02', { ...STAMP_1, generated_on: '2025-09-01' }, REPLAY_ROWS),
    },
    replayIndex([
      { id: '2026-01-02', schools: 4 },
      { id: DAY, schools: 4 },
      { id: '2026-01-07', schools: 4 },
      { id: '2026-01-09', schools: 4 },
    ]),
  );
  site = await serve(first.dir);
});

test.afterAll(async () => {
  await site?.stop();
  if (root !== '') rmSync(root, { recursive: true, force: true });
});

const at = (query = ''): string => `${site?.url ?? ''}${query}`;

test('the first view asks for no replay file and loads no replay code', async ({ browser }) => {
  const { page, context, requests, problems } = await visit(browser, at());
  await waitForLit(page, LIVE_ROWS.length);
  await expect(page.locator('.updated')).toHaveText(LIVE_LINE);
  expect(requests.filter((url) => /replay/iu.test(url))).toEqual([]);
  // The menu reads the index, once, under this build's own query; still no day file.
  await page.locator('.menu-button').click();
  await expect(page.locator('aside.menu [data-page="replay"]')).toBeVisible();
  const index = requests.filter((url) => url.includes('/data/replays/'));
  expect(index).toHaveLength(1);
  expect(index[0]).toMatch(/\/data\/replays\/index\.json\?v=[0-9a-f]{8}$/u);
  // Its replay page reads its first two days ahead of a press on one, each once.
  await page.locator('aside.menu [data-page="replay"]').click();
  await expect(page.locator('aside.menu .day')).toHaveCount(2);
  const days = (): string[] =>
    requests
      .filter((url) => url.includes('/data/replays/') && !url.includes('/index.json'))
      .map((url) => /\/replays\/(\d{4}-\d{2}-\d{2})\.[0-9a-f]+\.json$/u.exec(url)?.[1] ?? url)
      .sort();
  await expect.poll(days).toEqual(['2026-01-02', DAY]);
  expect(requests.filter((url) => url.includes('/data/replays/'))).toHaveLength(3);
  // Today's and a future day are never offered.
  await expect(page.locator('aside.menu .day')).toHaveText([
    `${DAY_TEXT}${format.replayReach(4, 1)}`,
    `Fri, Jan 2, 2026${format.replayReach(4, 1)}`,
  ]);
  expect(problems).toEqual([]);
  await context.close();
});

test('a day from the menu takes live’s place, says its date, and holds against live’s updates', async ({
  browser,
}) => {
  const { page, context, problems } = await visit(browser, at());
  await waitForLit(page, LIVE_ROWS.length);
  await expect.poll(() => legend(page)).toEqual(['2', '', '', '']);
  await enterFromMenu(page);
  await waitForLit(page, REPLAY_ROWS.length);
  await expect(page.locator(BAR)).toHaveText(`${format.replayLine(DAY)} ${copy.replay.exit}`);
  await expect(page.locator('.updated:not(.replay)')).toHaveCount(0);
  await expect.poll(() => legend(page)).toEqual(['2', '1', '1', '']);
  expect(new URL(page.url()).searchParams.get('replay')).toBe(DAY);
  await page.locator('.menu-button').click();
  await expect(page.locator('aside.menu h2').first()).toHaveText(DAY_TEXT);
  await expect(page.locator(`aside.menu [data-page="replay"]`)).toBeVisible();
  await page.keyboard.press('Escape');

  // Nothing on the page reads as live or today.
  expect(await page.locator('body').innerText()).not.toMatch(TODAY_WORDS);

  // Live goes on in the background: a newer live file, the worker's word of it, a return to
  // the tab. None of it shows while the replay is on.
  await page.route('**/data/live/closings.json*', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: closings(STAMP_1).replace(LIVE_AT, '2026-01-07T13:55:00Z'),
    }),
  );
  await page.evaluate((updatedURL) => {
    navigator.serviceWorker.dispatchEvent(
      new MessageEvent('message', {
        data: {
          type: 'CACHE_UPDATED',
          meta: 'workbox-broadcast-update',
          payload: { cacheName: 'snowlight-data-v1', updatedURL },
        },
      }),
    );
    document.dispatchEvent(new Event('visibilitychange'));
  }, new URL('data/live/closings.json', at()).href);
  await page.waitForTimeout(2_000);
  expect(await litCount(page)).toBe(REPLAY_ROWS.length);
  expect(await legend(page)).toEqual(['2', '1', '1', '']);
  await expect(page.locator(BAR)).toBeVisible();

  // A status picked in the menu counts the replay's schools, and is kept going back to live.
  await page.locator('.menu-button').click();
  await page.locator('aside.menu label', { hasText: copy.status.closed }).click();
  await waitForLit(page, 2);
  await page.keyboard.press('Escape');

  // Back to live: the update line, live's counts and lights, the address without the day.
  await page.locator(`${BAR} button`).click();
  await expect(page.locator(BAR)).toHaveCount(0);
  await expect(page.locator('.updated')).toHaveText(/^\s*Live · 7:5[05]\sAM$/u);
  await waitForLit(page, LIVE_ROWS.length);
  expect(new URL(page.url()).searchParams.has('replay')).toBe(false);
  expect(await page.locator('.stage').getAttribute('data-status')).toBe('0');
  await expect(page.locator('.menu-button')).toBeFocused();

  // Back returns to the replay, Forward to live, with no new entry.
  await page.goBack();
  await expect(page.locator(BAR)).toBeVisible();
  await waitForLit(page, 2);
  await page.goForward();
  await expect(page.locator(BAR)).toHaveCount(0);
  await waitForLit(page, LIVE_ROWS.length);
  expect(problems).toEqual([]);
  await context.close();
});

test('a link to a past day opens it with no frame of live, and its school’s panel is that day’s', async ({
  browser,
}) => {
  const cedar = SCHOOLS[2][0];
  const { page, context, problems, requests } = await visit(
    browser,
    at(`?replay=${DAY}&school=${cedar}`),
  );
  await waitForLit(page, REPLAY_ROWS.length);
  await expect(page.locator(BAR)).toBeVisible();
  // No paint ever lit live's two schools.
  const paints = await page.evaluate(() => (window as unknown as { __paints: number[] }).__paints);
  expect(paints).not.toContain(LIVE_ROWS.length);
  expect(await layoutShifts(page)).toEqual([]);

  const status = page.locator('.block.status');
  await expect(status.locator('.headline')).toHaveText('Closed Mon, Jan 5, 2026');
  await expect(status.locator('.line-note')).toHaveText(copy.reason.winterStorm);
  const panel = page.locator('aside', { has: status });
  expect(await panel.innerText()).not.toMatch(TODAY_WORDS);
  // Its neighbors' marks are the day's: Elm remote, Alder (closed today) none.
  const nearby = page.locator('.block.nearby li');
  await expect(nearby.nth(0).locator('.glyph')).toHaveClass(/is-remote/u);
  await expect(nearby.nth(1).locator('.glyph')).toHaveCount(0);
  // The panel read no live file for the day.
  const liveAfter = requests.filter((url) => url.includes('/data/live/'));
  expect(liveAfter.length).toBeLessThanOrEqual(1);

  // A school the day does not light has no status line at all.
  await page.goto(at(`?replay=${DAY}&school=${SCHOOLS[6][0]}`));
  await expect(page.locator('aside h2, aside .name').first()).toBeVisible();
  await waitForLit(page, REPLAY_ROWS.length);
  await expect(page.locator('.block.status')).toHaveCount(0);
  expect(await page.locator('body').innerText()).not.toMatch(TODAY_WORDS);
  expect(problems).toEqual([]);
  await context.close();
});

test('a ZIP code’s area on a past day counts that day under its date, with no chance', async ({
  browser,
}) => {
  const { page, context, problems } = await visit(browser, at(`?zip=64112&replay=${DAY}`));
  await waitForLit(page, REPLAY_ROWS.length);
  const tally = page.locator('.tally');
  await expect(tally.locator('.label')).toHaveText(DAY_TEXT);
  await expect(tally.locator('li')).toHaveText(['2 closed', '1 delayed', '1 remote']);
  await expect(page.locator('aside .number')).toHaveCount(0);
  expect(await page.locator('body').innerText()).not.toMatch(TODAY_WORDS);
  // Back to live: today's tally.
  await page.locator(`${BAR} button`).click();
  await expect(tally.locator('.label')).toHaveText(copy.days.today);
  await expect(tally.locator('li')).toHaveText(['2 closed']);
  expect(problems).toEqual([]);
  await context.close();
});

test('a day that cannot be shown leaves live as it is, and the address without it', async ({
  browser,
}) => {
  const context = await browser.newContext({ serviceWorkers: 'block', timezoneId: ZONE });
  for (const day of ['1999-01-01', '2026-01-07', '2026-01-09', 'nope', '2026-01-02']) {
    const { page } = await visit(browser, at(`?replay=${day}&zip=64112`), {}, context);
    await waitForLit(page, LIVE_ROWS.length);
    await expect(page.locator('.updated')).toHaveText(LIVE_LINE);
    await expect.poll(() => new URL(page.url()).search).toBe('?zip=64112');
    await expect(page.locator(BAR)).toHaveCount(0);
    await page.close();
  }
  // The day's file failing: live stays.
  const { page } = await visit(browser, at(), {}, context);
  await page.route('**/data/replays/2026-01-05.*.json', (route) => route.fulfill({ status: 500 }));
  await waitForLit(page, LIVE_ROWS.length);
  await enterFromMenu(page);
  await page.waitForTimeout(1_500);
  expect(await litCount(page)).toBe(LIVE_ROWS.length);
  await expect(page.locator(BAR)).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has('replay')).toBe(false);
  await context.close();
});

for (const width of [320, 390]) {
  test(`on a phone ${String(width)} px wide the day sits clear of the wordmark, field and button, and nothing shifts`, async ({
    browser,
  }) => {
    const { page, context, problems } = await visit(browser, at(), {
      ...devices['Pixel 7'],
      viewport: { width, height: 760 },
    });
    await waitForLit(page, LIVE_ROWS.length);
    await enterFromMenu(page);
    await waitForLit(page, REPLAY_ROWS.length);
    const bar = await page.locator(BAR).boundingBox();
    expect(bar).not.toBeNull();
    for (const selector of ['.wordmark', '.search', '.menu-button']) {
      const box = await page.locator(selector).first().boundingBox();
      if (bar === null || box === null) throw new Error(`no box for ${selector}`);
      const apart =
        bar.x >= box.x + box.width ||
        box.x >= bar.x + bar.width ||
        bar.y >= box.y + box.height ||
        box.y >= bar.y + bar.height;
      expect(apart, selector).toBe(true);
    }
    expect(bar?.x ?? -1).toBeGreaterThanOrEqual(0);
    expect((bar?.x ?? 0) + (bar?.width ?? 0)).toBeLessThanOrEqual(width);
    await page.locator(`${BAR} button`).click();
    await waitForLit(page, LIVE_ROWS.length);
    expect(await layoutShifts(page)).toEqual([]);
    expect(problems).toEqual([]);
    await context.close();
  });
}

test('a pressed day lights the map within a second on a throttled phone', async ({ browser }) => {
  const { page, context } = await visit(browser, at(), {
    ...devices['Pixel 7'],
  });
  await waitForLit(page, LIVE_ROWS.length);
  const cdp = await context.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 562.5,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
  });
  const times: number[] = [];
  for (let run = 0; run < 5; run++) {
    await openReplayPage(page);
    const row = page.locator('aside.menu .day', { hasText: DAY_TEXT });
    await row.waitFor();
    // The clock stops as the day's lights reach the glow layer, the last step the page takes:
    // the frame that draws them is the GPU's, here SwiftShader's in software on a shared
    // machine, which times the machine rather than the page.
    const took = await row.evaluate(
      (element, { id, count }) =>
        new Promise<number>((resolve, reject) => {
          const layer = window.snowlightMap?.getLayer(id) as unknown as
            | {
                implementation: {
                  setData: (points: unknown) => void;
                  stats: { count: number };
                };
              }
            | undefined;
          if (layer === undefined) {
            reject(new Error('no glow layer'));
            return;
          }
          const glow = layer.implementation;
          const setData = glow.setData.bind(glow);
          const started = performance.now();
          glow.setData = (points) => {
            setData(points);
            if (glow.stats.count !== count) return;
            Reflect.deleteProperty(glow, 'setData');
            resolve(performance.now() - started);
          };
          (element as HTMLElement).click();
        }),
      { id: GLOW_LAYER, count: REPLAY_ROWS.length },
    );
    times.push(took);
    await waitForLit(page, REPLAY_ROWS.length);
    await page.locator(`${BAR} button`).click();
    await waitForLit(page, LIVE_ROWS.length);
  }
  times.sort((a, b) => a - b);
  test.info().annotations.push({ type: 'tap to lit (ms)', description: times.join(', ') });
  console.warn(`tap to lit, ms, sorted: ${times.map((ms) => ms.toFixed(0)).join(', ')}`);
  expect(times[2]).toBeLessThan(1_000);
  await context.close();
});

test('after a deploy that stamps the day again, its new name is read and lights, and the old copies go', async ({
  browser,
}) => {
  if (site === undefined || first === undefined) throw new Error('no site');
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    timezoneId: ZONE,
  });
  try {
    const one = await visit(browser, at(), {}, context);
    await one.page.waitForFunction(() => navigator.serviceWorker.controller !== null, null, {
      timeout: 60_000,
    });
    await waitForLit(one.page, LIVE_ROWS.length);
    // What the deploy before this one left in the worker's caches: the day stamped for its
    // directory, under its own name, kept cache-first; and its replay index, with a day this
    // deploy dropped and a count of the day as it was, under the plain name and its own query.
    const data = new URL('data/', at()).href;
    const older = replay(DAY, { ...STAMP_1, generated_on: '2025-12-01' }, REPLAY_ROWS_OLD);
    const oldName = new URL(hashedPath(`replays/${DAY}.json`, sha256(older)), data).href;
    const oldIndex = replayIndex([
      { id: '2025-12-15', schools: 9 },
      { id: DAY, schools: REPLAY_ROWS_OLD.length },
    ]);
    await one.page.evaluate(
      async ({ caches: names, oldName: name, older: body, oldIndex: index, data: root }) => {
        const json = { headers: { 'Content-Type': 'application/json' } };
        await (await caches.open(names.staticData)).put(name, new Response(body, json));
        const live = await caches.open(names.data);
        await live.put(`${root}replays/index.json`, new Response(index, json));
        await live.put(`${root}replays/index.json?v=00000000`, new Response(index, json));
      },
      { caches: CACHE_NAMES, oldName, older, oldIndex, data },
    );
    await one.page.close();

    // The next visit: the menu offers this deploy's days with this deploy's counts, the day's
    // new name is read, it lights, and the copies the deploy before left are dropped.
    const two = await visit(browser, at(), {}, context);
    await waitForLit(two.page, LIVE_ROWS.length);
    await openReplayPage(two.page);
    await expect(two.page.locator('aside.menu .day')).toHaveText([
      `${DAY_TEXT}${format.replayReach(REPLAY_ROWS.length, 1)}`,
      `Fri, Jan 2, 2026${format.replayReach(4, 1)}`,
    ]);
    await two.page.locator('aside.menu .day', { hasText: DAY_TEXT }).click();
    await waitForLit(two.page, REPLAY_ROWS.length);
    const newName = new URL(first.replayNames[DAY] ?? '', data).href;
    expect(two.requests).toContain(newName);
    expect(two.requests).not.toContain(oldName);
    const kept = (name: string): Promise<string[]> =>
      two.page.evaluate(
        async (cacheName) => (await (await caches.open(cacheName)).keys()).map(({ url }) => url),
        name,
      );
    await expect.poll(() => kept(CACHE_NAMES.staticData)).not.toContain(oldName);
    await expect
      .poll(() => kept(CACHE_NAMES.data))
      .not.toContain(`${data}replays/index.json?v=00000000`);
  } finally {
    await context.close();
  }
});

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

import { devices, expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { copy } from '../src/copy';
import { FLIGHT_LEAD } from '../src/map/basemap/flight';
import { HELD_FRAME_CLASS } from '../src/map/basemap/held-frame';
import { BASEMAP_IDS } from '../src/map/basemap/ids';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const PIPELINE_OUT = path.join(WEB, '../pipeline/out');
const SITE_DATA = path.join(PIPELINE_OUT, 'site-data');
const GLOW_LAYER = 'snowlight-glow';
const PEMBROKE_HILL = { id: 'A1902690', lon: -94.593001, lat: 39.03606 };
const PEMBROKE_HILL_NAME = 'The Pembroke Hill School - Wornall Campus';
/** Named "ELEMENTARY SCHOOL" by the directory, under Citizens of the World Charter. */
const CITIZENS_ELEMENTARY = '290061203286';
/** "ALLEN VILLAGE ELEMENTARY ACADE" in the directory: 30 characters, all Missouri keeps. */
const ALLEN_VILLAGE_ELEMENTARY = '290002502748';
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

/** Every school's NCES id and place, from the directory the pipeline wrote (points.bin). */
function directory(): { id: string; lon: number; lat: number }[] {
  const meta = JSON.parse(readFileSync(path.join(SITE_DATA, 'schools/meta.json'), 'utf8')) as {
    ids: string[];
  };
  const points = readFileSync(path.join(SITE_DATA, 'schools/points.bin'));
  // A 16-byte header, then 13 bytes a school: longitude and latitude in millionths of a degree.
  return meta.ids.map((id, i) => ({
    id,
    lon: points.readInt32LE(16 + 13 * i) / 1e6,
    lat: points.readInt32LE(20 + 13 * i) / 1e6,
  }));
}

/** How many of the directory's schools are private: kind flag 0x01, the 13th byte of each record. */
function privateSchools(): number {
  const points = readFileSync(path.join(SITE_DATA, 'schools/points.bin'));
  let count = 0;
  for (let at = 16; at + 13 <= points.length; at += 13) count += points.readUInt8(at + 12) & 1;
  return count;
}

/** The ids of the schools the directory puts inside the map's view. */
async function schoolsInView(page: Page): Promise<Set<string>> {
  const bounds = await page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const box = map.getBounds();
    return {
      west: box.getWest(),
      east: box.getEast(),
      south: box.getSouth(),
      north: box.getNorth(),
    };
  });
  return new Set(
    directory()
      .filter(
        ({ lon, lat }) =>
          lon > bounds.west && lon < bounds.east && lat > bounds.south && lat < bounds.north,
      )
      .map(({ id }) => id),
  );
}

/** Pembroke Hill's zoom-14 street tile, the deepest OpenFreeMap has: z/x/y. */
const PEMBROKE_HILL_STREET_TILE = '/14/3886/6259.pbf';

/** Whether the map keeps loading the tiles it has zoomed past, as it does during a flight. */
async function keepsTiles(page: Page): Promise<boolean> {
  return page.evaluate(() => window.snowlightMap?.cancelPendingTileRequestsWhileZooming === false);
}

/** Where Pembroke Hill is on the screen, in CSS pixels. */
async function schoolOnScreen(page: Page): Promise<{ x: number; y: number }> {
  return page.evaluate(({ lon, lat }) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const point = map.project([lon, lat]);
    const box = map.getContainer().getBoundingClientRect();
    return { x: box.left + point.x, y: box.top + point.y };
  }, PEMBROKE_HILL);
}

/**
 * Resolves once the map is where a pick of Pembroke Hill takes it on a wide screen: at zoom 15,
 * with the school in the middle of what its panel leaves in view.
 */
async function expectLandedBesidePanel(page: Page): Promise<void> {
  const panel = page.locator('aside.detail');
  await expect
    .poll(
      async () => {
        const view = await mapView(page);
        const where = await schoolOnScreen(page);
        // The panel's own width: wider on a wide screen (app/frame.ts PANEL_WIDTHS).
        const box = await panel.boundingBox();
        const panelRight = (box?.x ?? 0) + (box?.width ?? 0);
        return (
          Math.abs(view.zoom - 15) < 0.05 &&
          Math.abs(where.x - (panelRight + 1440) / 2) < 3 &&
          Math.abs(where.y - (64 + 900) / 2) < 3
        );
      },
      { timeout: 60_000 },
    )
    .toBe(true);
}

/** The cursor over the map. */
async function mapCursor(page: Page): Promise<string> {
  return page.evaluate(() => {
    const canvas = document.querySelector('.maplibregl-canvas');
    return canvas === null ? '' : getComputedStyle(canvas).cursor;
  });
}

/**
 * How far the nearest dot MapLibre drew other than Pembroke Hill's is from a point on the
 * screen, in CSS pixels, or Infinity: how clear of other schools a click there is.
 */
async function nearestOtherSchool(page: Page, x: number, y: number): Promise<number> {
  return page.evaluate(
    ({ x, y, layers, id }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const box = map.getContainer().getBoundingClientRect();
      const distances = map
        .queryRenderedFeatures({ layers })
        .filter((feature) => feature.properties.id !== id)
        .map((feature) => {
          const [lon, lat] = (feature.geometry as { coordinates: [number, number] }).coordinates;
          const at = map.project([lon, lat]);
          return Math.hypot(box.left + at.x - x, box.top + at.y - y);
        });
      return Math.min(Infinity, ...distances);
    },
    { x, y, layers: [BASEMAP_IDS.schoolDots], id: PEMBROKE_HILL.id },
  );
}

/**
 * A point on the map well clear of every school MapLibre drew, dot or name, and of the page's
 * controls: where a click means no school. With `shift`, one from which a drag by that much
 * ends on the map too, clear of its controls.
 */
async function clearSpot(
  page: Page,
  shift: { x: number; y: number } = { x: 0, y: 0 },
): Promise<{ x: number; y: number }> {
  return page.evaluate(
    ({ layers, shift }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const box = map.getContainer().getBoundingClientRect();
      const marks = map.queryRenderedFeatures({ layers }).map((feature) => {
        const [lon, lat] = (feature.geometry as { coordinates: [number, number] }).coordinates;
        return map.project([lon, lat]);
      });
      // Right of where a panel opens, under the search strip, clear of the corners' controls.
      const inside = (x: number, y: number): boolean =>
        x >= 600 && x <= box.width - 120 && y >= 200 && y <= box.height - 200;
      for (let y = 200; y <= box.height - 200; y += 20) {
        for (let x = 600; x <= box.width - 120; x += 20) {
          if (
            inside(x + shift.x, y + shift.y) &&
            marks.every((at) => Math.hypot(at.x - x, at.y - y) > 80)
          ) {
            return { x: box.left + x, y: box.top + y };
          }
        }
      }
      throw new Error('no spot clear of every school');
    },
    { layers: [BASEMAP_IDS.schoolDots, BASEMAP_IDS.schoolNames], shift },
  );
}

async function mapView(page: Page): Promise<{ lat: number; lon: number; zoom: number }> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
  });
}

/** A frame the map drew: how much of it was lit, and what it drew it from. */
interface Frame {
  zoom: number;
  lat: number;
  lon: number;
  /** Pixels lit, of `read`: every fourth row read back. */
  lit: number;
  read: number;
  /** The same, of the view a cut left, held over the map (held-frame.ts), while it is shown whole. */
  held: number | null;
  /** The view the address names. */
  at: string | null;
  /** The zoom of the coarsest street tiles drawn. */
  coarsest: number | null;
}

/** Records every frame the map draws from here on (recordedFrames). */
async function recordFrames(page: Page): Promise<void> {
  await page.evaluate(
    ({ streets, heldClass }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const gl = map.getCanvas().getContext('webgl2');
      if (gl === null) throw new Error('no WebGL 2');
      const frames: Frame[] = [];
      (window as unknown as { frames_: Frame[] }).frames_ = frames;
      const lit = (row: Uint8Array | Uint8ClampedArray, width: number): number => {
        let count = 0;
        for (let x = 0; x < width; x++) {
          const i = x * 4;
          if (Math.max(row[i] ?? 0, row[i + 1] ?? 0, row[i + 2] ?? 0) > 8) count++;
        }
        return count;
      };
      const coarsest = (): number | null => {
        const tiles = map.style.tileManagers[streets];
        if (tiles === undefined) return null;
        const zooms = tiles
          .getRenderableIds()
          .map((id) => tiles.getTileByID(id)?.tileID.overscaledZ ?? Number.POSITIVE_INFINITY);
        const least = Math.min(...zooms);
        return Number.isFinite(least) ? least : null;
      };
      const heldLit = (): number | null => {
        const held = document.querySelector(`canvas.${heldClass}`);
        if (!(held instanceof HTMLCanvasElement) || getComputedStyle(held).opacity !== '1') {
          return null;
        }
        // Read from a copy made for reading, so the page's own canvas is never read back.
        const copy = document.createElement('canvas');
        copy.width = held.width;
        copy.height = held.height;
        const context = copy.getContext('2d', { willReadFrequently: true });
        if (context === null) return null;
        context.drawImage(held, 0, 0);
        const pixels = context.getImageData(0, 0, copy.width, copy.height).data;
        let count = 0;
        for (let y = 1; y < copy.height; y += 4) {
          const start = y * copy.width * 4;
          count += lit(pixels.subarray(start, start + copy.width * 4), copy.width);
        }
        return count;
      };
      map.on('render', () => {
        const width = gl.drawingBufferWidth;
        const height = gl.drawingBufferHeight;
        const row = new Uint8Array(width * 4);
        let count = 0;
        let read = 0;
        for (let y = 1; y < height; y += 4) {
          gl.readPixels(0, y, width, 1, gl.RGBA, gl.UNSIGNED_BYTE, row);
          count += lit(row, width);
          read += width;
        }
        const center = map.getCenter();
        frames.push({
          zoom: map.getZoom(),
          lat: center.lat,
          lon: center.lng,
          lit: count,
          read,
          held: heldLit(),
          at: new URL(location.href).searchParams.get('at'),
          coarsest: coarsest(),
        });
      });
    },
    { streets: BASEMAP_IDS.openFreeMapSource, heldClass: HELD_FRAME_CLASS },
  );
}

/** The frames drawn since recordFrames. */
async function recordedFrames(page: Page): Promise<Frame[]> {
  return page.evaluate(() => (window as unknown as { frames_: Frame[] }).frames_);
}

/**
 * The frames a viewer saw blank: less than a thousandth of the frame lit, as when the map drew
 * only the black ground above zoom 7 while the street tiles were still coming. A frame under the
 * view a cut left, held whole over it, shows that view.
 */
function blankFrames(frames: readonly Frame[]): string[] {
  return frames
    .filter((frame) => (frame.held ?? frame.lit) < frame.read / 1000)
    .map((frame) => `zoom ${frame.zoom.toFixed(2)}: ${String(frame.held ?? frame.lit)} lit`);
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
  // The school details, staged from the directory's tables: an index and a file per 256 schools.
  const details = shipped.filter((file) => file.startsWith('schools/details/'));
  const meta = JSON.parse(readFileSync(path.join(SITE_DATA, 'schools/meta.json'), 'utf8')) as {
    count: number;
  };
  expect(details).toHaveLength(Math.ceil(meta.count / 256) + 1);
  for (const file of details) {
    expect(file).toMatch(/^schools\/details\/(?:\d+|index)\.[0-9a-f]{10}\.json$/);
    expect(file).toContain(sha256(path.join(data, file)).slice(0, 10));
  }
  // Everything else the pipeline published, as it wrote it; never its own records or the index inputs.
  const rest = shipped.filter(
    (file) =>
      !/^(schools\/(meta|points|schools)|search-index)\.[0-9a-f]{10}\./.test(file) &&
      !details.includes(file),
  );
  for (const file of rest) {
    expect(sha256(path.join(data, file))).toBe(sha256(path.join(SITE_DATA, file)));
  }
  expect(shipped.filter((file) => /internal|\.jsonl$|^search\//.test(file))).toEqual([]);
  expect(shipped).toHaveLength(rest.length + details.length + 4);
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
      { implementation: { stats: { count: number; glowCount: number; dust: number } } } | undefined;
    return layer?.implementation.stats;
  }, GLOW_LAYER);
  // No school as dust either: the national view shows only what schools say today.
  expect(glow).toMatchObject({ count: 0, glowCount: 0, dust: 0 });
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

test('the menu counts every school and district on the map, and nothing the pipeline has not published', async ({
  browser,
}) => {
  const meta = JSON.parse(readFileSync(path.join(SITE_DATA, 'schools/meta.json'), 'utf8')) as {
    count: number;
    districts: { ids: string[] };
  };
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems, requests } = watch(page);
  await page.goto(site);
  await settle(page);
  await page.getByRole('button', { name: copy.menu.label, exact: true }).click();
  const menu = page.locator('aside.menu');
  await expect(menu).toBeVisible();
  // What the map shows today and which schools, then a season or a track record, only once the
  // pipeline publishes one, and About.
  const published = (file: string): boolean => existsSync(path.join(SITE_DATA, file));
  await expect(menu.locator('h2')).toHaveText([copy.menu.today, copy.menu.kinds]);
  await expect(menu.locator('button.item .name')).toHaveText([
    ...(published('stats/season.json') ? [copy.nav.seasonStats] : []),
    ...(published('track-record.json') ? [copy.nav.trackRecord] : []),
    copy.nav.about,
  ]);
  // Nothing lit in September: no status gives a count.
  if (!published('live/closings.json')) {
    await expect(menu.locator('.value:not(:empty)')).toHaveCount(0);
  }
  // Under the search field, its left edge on the field's, once it has slid into place.
  await menu.evaluate(async (node) => {
    await Promise.all(node.getAnimations().map((animation) => animation.finished));
  });
  const field = await page.locator('.search').boundingBox();
  const panel = await menu.boundingBox();
  if (field === null || panel === null) throw new Error('no box');
  expect([panel.x, panel.y]).toEqual([field.x, field.y + field.height + 8]);

  // About counts the directory as the pipeline wrote it, on the list's grid: each label where
  // the list's names start, each value ending where its arrows do, level with its label.
  const edges = await menu.evaluate((found) => {
    const left = (element: Element | null): number =>
      Math.round(element?.getBoundingClientRect().left ?? -1);
    const right = (element: Element | null): number =>
      Math.round(element?.getBoundingClientRect().right ?? -1);
    return {
      name: left(found.querySelector('.item .name')),
      end: right(found.querySelector('.item .more')),
    };
  });
  await menu.getByRole('button', { name: copy.nav.about }).click();
  await expect(menu.locator('.note')).toHaveText([copy.menu.onMap]);
  const rows = await menu.locator('.row').evaluateAll((found) =>
    found.map((row) => {
      const words = (cell: Element | null): DOMRect => {
        const range = document.createRange();
        if (cell !== null) range.selectNodeContents(cell);
        return range.getBoundingClientRect();
      };
      const label = row.querySelector('dt');
      const value = row.querySelector('dd');
      const text = label?.lastChild ?? null;
      const range = document.createRange();
      if (text !== null) {
        const content = text.textContent ?? '';
        range.selectNodeContents(text);
        range.setStart(text, content.length - content.trimStart().length);
      }
      const start = range.getBoundingClientRect();
      const end = words(value);
      return {
        cells: [label?.textContent.trim() ?? '', value?.textContent.trim() ?? ''],
        left: Math.round(start.left),
        right: Math.round(end.right),
        level: Math.round(end.top - start.top),
      };
    }),
  );
  expect(rows.map((row) => row.cells)).toEqual([
    [copy.menu.schools, meta.count.toLocaleString('en-US')],
    [copy.menu.districts, meta.districts.ids.length.toLocaleString('en-US')],
  ]);
  for (const row of rows) {
    expect([row.left, row.right, row.level]).toEqual([edges.name, edges.end, 0]);
  }
  // The directory's small index is all it reads for them (once more through the service worker,
  // which keeps a copy of what the page read before it took over).
  const read = requests
    .map((request) => new URL(request.url).pathname)
    .filter((pathname) => pathname.includes('/data/'));
  expect(read.length).toBeGreaterThan(0);
  for (const pathname of read) {
    expect(pathname).toMatch(/\/data\/schools\/details\/index\.[0-9a-f]{10}\.json$/);
  }
  expect(problems).toEqual([]);
  await context.close();
});

test('the menu shows the dots, dust and names of public schools, private ones or both', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  // Across Missouri, where the glow layer draws every school as dust.
  await page.goto(`${site}?at=39.1,-94.6,7`);
  await settle(page);
  /** How many schools the dust holds, and how many it leaves out. */
  const dust = (): Promise<{ dust: number; dustHidden: number } | undefined> =>
    page.evaluate((id) => {
      const layer = window.snowlightMap?.getLayer(id) as unknown as
        { implementation: { stats: { dust: number; dustHidden: number } } } | undefined;
      const stats = layer?.implementation.stats;
      return stats === undefined ? undefined : { dust: stats.dust, dustHidden: stats.dustHidden };
    }, GLOW_LAYER);
  const all = directory().length;
  const privates = privateSchools();
  await expect.poll(dust, { timeout: 60_000 }).toEqual({ dust: all, dustHidden: 0 });
  // The map takes the school layers on a little after its first frames.
  await page.waitForFunction(
    () => window.snowlightMap?.getLayer('school-dots') !== undefined,
    null,
    {
      timeout: 30_000,
    },
  );
  const layers = ['school-dots', 'school-light', 'school-names', 'school-space'];
  const filters = (): Promise<unknown[]> =>
    page.evaluate(
      (ids) => ids.map((id) => window.snowlightMap?.getFilter(id) ?? null),
      [...layers, 'school-selected'],
    );
  const [, , , , ring] = await filters();
  await page.getByRole('button', { name: copy.menu.label, exact: true }).click();
  const menu = page.locator('aside.menu');
  const toggle = async (name: string): Promise<void> => {
    await menu.locator('label.item', { hasText: name }).click();
  };
  // A private school's tiles carry kind flags with 0x01 set (pipeline/snowlight/directory/tiles.py).
  const privateSchool = ['==', ['%', ['to-number', ['get', 'kind'], 0], 2], 1];
  // The dust leaves out the same schools, by the kind flags points.bin carries.
  await toggle(copy.menu.private);
  await expect.poll(filters).toEqual([...layers.map(() => ['any', ['!', privateSchool]]), ring]);
  await expect.poll(dust).toEqual({ dust: all, dustHidden: privates });
  await toggle(copy.menu.public);
  await expect.poll(filters).toEqual([...layers.map(() => false), ring]);
  await expect.poll(dust).toEqual({ dust: all, dustHidden: all });
  await toggle(copy.menu.private);
  await expect.poll(filters).toEqual([...layers.map(() => ['any', privateSchool]), ring]);
  await expect.poll(dust).toEqual({ dust: all, dustHidden: all - privates });
  // Both again: every school, as the map opened.
  await toggle(copy.menu.public);
  await expect.poll(filters).toEqual([...layers.map(() => null), ring]);
  await expect.poll(dust).toEqual({ dust: all, dustHidden: 0 });
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
  // The index is asked for once, whenever the service worker takes the page over: a file the
  // page reads before then is kept for the worker as it is read (src/data/files.ts fetchFile).
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
  // It lands in the school's panel: the name, what the school is and where, from the directory.
  const panel = page.locator('aside.detail');
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
  await expect(panel.locator('.kind')).toHaveText(`${copy.detail.privateSchool} · PK–12`);
  await expect(panel.locator('.place')).toHaveText('Kansas City, MO · Jackson County');
  await expect(panel.locator('.fact dt')).toHaveText([
    copy.detail.students,
    copy.detail.address,
    copy.detail.phone,
  ]);
  await expect(panel.locator('.fact dd')).toHaveText([
    '1,174',
    '400 W 51st StKansas City, MO 64112',
    /^\(816\)\s936-1230$/,
  ]);
  // It is September: no status, and no chance card without the history to give a chance.
  await expect(panel.locator('.outlook')).toHaveCount(0);
  await expect(panel.locator('.status')).toHaveCount(0);
  // The schools nearest it, by the directory's places, nearest first.
  await expect(panel.locator('.near-name')).toHaveText([
    'Visitation Catholic School',
    "St Teresa's Academy",
    'Allen Village High School',
    'Allen Village Elementary Academy',
  ]);
  await expect(panel.locator('.near-distance')).toHaveText([
    `0.3\u00a0mi`,
    `0.7\u00a0mi`,
    `1.1\u00a0mi`,
    `1.2\u00a0mi`,
  ]);
  // Its dot is ringed on the map, the one the panel is about.
  await expect
    .poll(
      () =>
        page.evaluate((id) => {
          const map = window.snowlightMap;
          return map?.getLayer(id) === undefined ? null : map.getFilter(id);
        }, BASEMAP_IDS.schoolSelected),
      { timeout: 30_000 },
    )
    .toEqual(['==', ['get', 'id'], PEMBROKE_HILL.id]);
  await expectLandedBesidePanel(page);
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

test('a link to Pembroke Hill lands as picking it does: its streets, right of the panel', async ({
  browser,
}) => {
  // Two landings, each waited for up to 90 s.
  test.setTimeout(240_000);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  /** Where the map comes to rest, once it has: its zoom, and the school on the screen. */
  const landing = async (page: Page): Promise<{ zoom: number; x: number; y: number }> => {
    let last = '';
    await expect
      .poll(
        async () => {
          await settle(page);
          const { lat, lon, zoom } = await mapView(page);
          const now = `${lat.toFixed(6)},${lon.toFixed(6)},${zoom.toFixed(3)}`;
          const still = now === last;
          last = now;
          return still;
        },
        { timeout: 90_000, intervals: [1000] },
      )
      .toBe(true);
    return { zoom: (await mapView(page)).zoom, ...(await schoolOnScreen(page)) };
  };

  const picked = await context.newPage();
  const { problems } = watch(picked);
  await picked.goto(site);
  await settle(picked);
  const input = picked.locator('input.search-input');
  await input.click();
  await input.pressSequentially('pembroke', { delay: 20 });
  await picked.locator('[role="option"]', { hasText: PEMBROKE_HILL_NAME }).click();
  await expect(picked.locator('aside.detail h2')).toHaveText(
    'The Pembroke Hill SchoolWornall Campus',
  );
  const pick = await landing(picked);

  const linked = await context.newPage();
  const linkProblems = watch(linked).problems;
  await linked.goto(`${site}?school=${PEMBROKE_HILL.id}`);
  const panel = linked.locator('aside.detail');
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
  const link = await landing(linked);
  const box = await panel.boundingBox();
  const panelRight = (box?.x ?? 0) + (box?.width ?? 0);

  // The same zoom, the school at the same spot, but for the search index's rounding of its
  // place (up to 6 m, 3 pixels here): the middle of the map the panel leaves in view.
  expect(link.zoom).toBeCloseTo(pick.zoom, 2);
  expect(link.zoom).toBeCloseTo(15, 2);
  expect(Math.abs(link.x - pick.x)).toBeLessThan(4);
  expect(Math.abs(link.y - pick.y)).toBeLessThan(4);
  expect(Math.abs(link.x - (panelRight + 1440) / 2)).toBeLessThan(3);
  expect(Math.abs(link.y - (64 + 900) / 2)).toBeLessThan(3);
  expect([...problems, ...linkProblems]).toEqual([]);
  await context.close();
});

test('looking at Kansas City, “Pembroke” lists Pembroke Hill first, above Pembroke, Massachusetts', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  const rows = async (): Promise<string[]> =>
    page
      .locator('[role="option"]')
      .evaluateAll((all) =>
        all.map((option) => (option instanceof HTMLElement ? option.innerText : '')),
      );

  // The metro, as someone there sees it.
  await page.goto(`${site}?at=39.1,-94.58,10`);
  await settle(page);
  const input = page.locator('input.search-input');
  await input.click();
  await input.pressSequentially('Pembroke', { delay: 20 });
  const options = page.locator('[role="option"]');
  await expect(options.first()).toContainText(PEMBROKE_HILL_NAME, { timeout: 30_000 });
  await expect(options.first()).toContainText('Kansas City, MO');
  await expect(options.first()).toHaveClass(/is-target/);
  const near = await rows();
  const massachusetts = near.findIndex((row) => row.includes('Pembroke, MA'));
  expect(massachusetts).toBeGreaterThan(0);
  // Its section comes first, the others after it, each still in the list.
  await expect(page.locator('[role="listbox"] > [role="group"]').first()).toHaveAccessibleName(
    copy.search.sections.school,
  );

  // From the national view nothing is near: the places named Pembroke lead, as before.
  await page.goto(site);
  await settle(page);
  await input.click();
  await input.pressSequentially('Pembroke', { delay: 20 });
  await expect(options.first()).not.toContainText(PEMBROKE_HILL_NAME, { timeout: 30_000 });
  await expect(page.locator('[role="listbox"] > [role="group"]').first()).toHaveAccessibleName(
    copy.search.sections.city,
  );
  expect(await rows()).toEqual(
    expect.arrayContaining([expect.stringContaining(PEMBROKE_HILL_NAME)]),
  );
  expect(problems).toEqual([]);
  await context.close();
});

test('a school’s name typed as the map shows it finds that school first, its name whole', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  await page.goto(`${site}?at=39.06,-94.59,12`);
  await settle(page);
  const input = page.locator('input.search-input');
  const first = page.locator('[role="option"]').first();
  /** Whether a row's name shows less than all of itself. */
  const cut = (): Promise<boolean> =>
    first
      .locator('.name')
      .evaluate(
        (name) =>
          name.scrollWidth > name.clientWidth + 1 || name.scrollHeight > name.clientHeight + 1,
      );
  // Typed as the map names them, whole or in part: a generic name under its charter, a name NCES
  // cut off, and shortenings the page spells out.
  const typed: [string, string][] = [
    [
      'Citizens of the World Charter - Middle School',
      'Citizens of the World Charter - Middle School',
    ],
    [
      'citizens of the world charter elementary',
      'Citizens of the World Charter - Elementary School',
    ],
    ['citizens middle', 'Citizens of the World Charter - Middle School'],
    ['allen village elementary academy', 'Allen Village Elementary Academy'],
    ['missouri school for the deaf', 'Missouri School for the Deaf'],
    ['five county regional vocational center', 'Five County Regional Vocational Center'],
  ];
  await input.click();
  for (const [text, name] of typed) {
    await input.fill(text);
    await expect(first.locator('.name'), text).toHaveText(name, { timeout: 30_000 });
    expect(await cut(), name).toBe(false);
  }
  // Both of the charter's Kansas City schools are among the schools of that name.
  await input.fill('citizens of the world');
  await expect(page.locator('[role="option"]', { hasText: 'Middle School' })).toHaveCount(1, {
    timeout: 30_000,
  });
  await expect(page.locator('[role="option"]', { hasText: 'Elementary School' })).toHaveCount(1);

  // Picked, the field holds the name the map draws it by, and it finds the school again.
  await input.fill('citizens of the world charter elementary');
  await expect(first).toContainText('Citizens of the World Charter - Elementary School', {
    timeout: 30_000,
  });
  await first.click();
  await expect(input).toHaveValue('Citizens of the World Charter - Elementary School');
  await expect
    .poll(() => new URL(page.url()).searchParams.get('school'), { timeout: 30_000 })
    .toBe(CITIZENS_ELEMENTARY);
  await expect
    .poll(async () => (await mapView(page)).zoom, { timeout: 30_000 })
    .toBeGreaterThan(14.9);
  await settle(page);
  expect(await drawn(page, BASEMAP_IDS.schoolNames)).toContainEqual({
    id: CITIZENS_ELEMENTARY,
    name: 'Citizens of the World Charter - Elementary School',
  });
  await input.fill('');
  await input.fill('Citizens of the World Charter - Elementary School');
  await expect(first.locator('.name')).toHaveText(
    'Citizens of the World Charter - Elementary School',
    { timeout: 30_000 },
  );
  expect(problems).toEqual([]);
  await context.close();
});

test('flying from the national view to a school, no frame on the way is blank', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  await page.goto(site);
  await settle(page);
  const input = page.locator('input.search-input');
  await input.click();
  await input.pressSequentially('pembroke', { delay: 20 });
  const option = page.locator('[role="option"]', { hasText: PEMBROKE_HILL_NAME });
  await expect(option).toHaveCount(1, { timeout: 30_000 });

  await recordFrames(page);
  await option.click();
  await expect
    .poll(
      async () => {
        const view = await mapView(page);
        return Math.abs(view.zoom - 15) < 0.05;
      },
      { timeout: 60_000 },
    )
    .toBe(true);
  await settle(page);
  const frames = await recordedFrames(page);
  // The flight went from the national view through the handover to the street tiles at zoom 7
  // and on to the school.
  expect(frames.length).toBeGreaterThan(10);
  expect(Math.min(...frames.map((frame) => frame.zoom))).toBeLessThan(6);
  expect(frames.filter((frame) => frame.zoom > 7.5).length).toBeGreaterThan(3);
  expect(blankFrames(frames)).toEqual([]);
  // Past the handover every frame draws street tiles: the flight waited at its stop for the first
  // ones, and went in no faster than closer ones came (flight.ts).
  const bare = frames.filter((frame) => frame.zoom >= 7.5 && frame.coarsest === null);
  expect(bare.map((frame) => `zoom ${frame.zoom.toFixed(2)}`)).toEqual([]);
  // The address names where the map is going all the way, never a view on the way there.
  const addresses = new Set(frames.map((frame) => frame.at));
  for (const at of addresses) expect(Number(at?.split(',')[2]), String(at)).toBeGreaterThan(14.9);
  expect(problems).toEqual([]);
  await context.close();
});

test('from the metro, Pembroke Hill on the screen glides in, no frame on the way blank', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  await page.goto(`${site}?at=39.1,-94.58,10`);
  await settle(page);
  const input = page.locator('input.search-input');
  await input.click();
  await input.pressSequentially('pembroke', { delay: 20 });
  const option = page.locator('[role="option"]', { hasText: PEMBROKE_HILL_NAME });
  await expect(option).toHaveCount(1, { timeout: 30_000 });
  await recordFrames(page);
  await option.click();
  await expect
    .poll(async () => Math.abs((await mapView(page)).zoom - 15) < 0.05, { timeout: 60_000 })
    .toBe(true);
  await settle(page);
  const frames = await recordedFrames(page);
  // A glide: no view held over the map, no zooming out on the way, streets in every frame.
  expect(frames.filter((frame) => frame.held !== null)).toEqual([]);
  expect(Math.min(...frames.map((frame) => frame.zoom))).toBeGreaterThan(9.99);
  expect(blankFrames(frames)).toEqual([]);
  expect(frames.filter((frame) => frame.coarsest === null)).toEqual([]);
  expect(problems).toEqual([]);
  await context.close();
});

/**
 * Places off the screen at Pembroke Hill: a school across the state line and a city far off,
 * arrived at from FLIGHT_LEAD levels out, and the city it is in, cut to straight.
 */
const OFF_SCREEN = [
  {
    name: 'a school across town',
    query: 'Miege',
    pick: /^\s*Bishop Miege High School\b/,
    straight: false,
  },
  { name: 'another city', query: 'Denver', pick: /^\s*Denver\s+Colorado\s*$/, straight: false },
  {
    name: 'the city around it',
    query: 'Kansas City',
    pick: /^\s*Kansas City\s+Missouri\s*$/,
    straight: true,
  },
] as const;

for (const { name, query, pick, straight } of OFF_SCREEN) {
  test(`from a school’s streets to ${name} off the screen, the view it leaves stays until the new one is drawn`, async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const { problems } = watch(page);
    await page.goto(`${site}?at=${String(PEMBROKE_HILL.lat)},${String(PEMBROKE_HILL.lon)},15`);
    await settle(page);
    const start = await mapView(page);
    const input = page.locator('input.search-input');
    await input.click();
    await input.pressSequentially(query, { delay: 20 });
    const option = page.locator('[role="option"]', { hasText: pick });
    await expect(option).toHaveCount(1, { timeout: 30_000 });
    // The address names where it is going from the start; the map gets there.
    const at = (): Promise<string | null> =>
      page.evaluate(() => new URL(location.href).searchParams.get('at'));
    const before = await at();
    await recordFrames(page);
    await option.click();
    await expect.poll(at).not.toBe(before);
    const [lat = NaN, lon = NaN, zoom = NaN] = ((await at()) ?? '').split(',').map(Number);
    await expect
      .poll(
        async () => {
          const view = await mapView(page);
          return (
            Math.abs(view.lat - lat) < 1e-3 &&
            Math.abs(view.lon - lon) < 1e-3 &&
            Math.abs(view.zoom - zoom) < 0.05
          );
        },
        { timeout: 60_000 },
      )
      .toBe(true);
    await settle(page);
    const frames = await recordedFrames(page);
    // It cut there instead of flying over streets the map had none of: every frame is over one
    // place or the other, the one it left held on screen while the map drew the other, then gone.
    const between = frames.filter(
      (frame) =>
        !(Math.abs(frame.lat - start.lat) < 1e-6 && Math.abs(frame.lon - start.lon) < 1e-6) &&
        !(Math.abs(frame.lat - lat) < 1e-3 && Math.abs(frame.lon - lon) < 1e-3),
    );
    expect(between.map((frame) => `${frame.lat.toFixed(3)},${frame.lon.toFixed(3)}`)).toEqual([]);
    expect(frames.filter((frame) => frame.held !== null).length).toBeGreaterThan(0);
    // Around the place it left, straight to the view; elsewhere, from FLIGHT_LEAD levels out.
    const there = frames.filter((frame) => Math.abs(frame.lon - start.lon) > 1e-6);
    const closest = straight ? zoom : zoom - FLIGHT_LEAD;
    expect(Math.min(...there.map((frame) => frame.zoom))).toBeGreaterThan(closest - 0.01);
    if (!straight) expect(Math.min(...there.map((frame) => frame.zoom))).toBeLessThan(zoom - 1);
    expect(await page.locator(`canvas.${HELD_FRAME_CLASS}`).count()).toBe(0);
    expect(blankFrames(frames)).toEqual([]);
    // Past the handover every frame not under the held view draws street tiles.
    const bare = frames.filter(
      (frame) => frame.held === null && frame.zoom >= 7.5 && frame.coarsest === null,
    );
    expect(bare.map((frame) => `zoom ${frame.zoom.toFixed(2)}`)).toEqual([]);
    expect(problems).toEqual([]);
    await context.close();
  });
}

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

test('every school in view is a dot across a metro, and named from zoom 13, never one name over another', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems, requests } = watch(page);
  const tileRequests = (): number =>
    requests.filter((request) => SCHOOL_TILES.test(request.url)).length;

  // Kansas City: the region, the metro, the Plaza, Pembroke Hill.
  await page.goto(`${site}?at=39.03,-94.58,8.6`);
  await settle(page);
  expect(await drawn(page, BASEMAP_IDS.schoolDots)).toEqual([]);
  expect(tileRequests()).toBe(0);
  // Across the region every school is dust instead, drawn by the glow layer from the directory's
  // own positions (points.bin).
  await page.waitForFunction(
    (id) => {
      const layer = window.snowlightMap?.getLayer(id) as unknown as
        { implementation: { stats: { dust: number; dustDrawn: boolean } } } | undefined;
      const stats = layer?.implementation.stats;
      return stats !== undefined && stats.dust > 0 && stats.dustDrawn;
    },
    GLOW_LAYER,
    { timeout: 30_000 },
  );
  const dust = await page.evaluate((id) => {
    const layer = window.snowlightMap?.getLayer(id) as unknown as {
      implementation: { stats: { dust: number; dustInView: number } };
    };
    return layer.implementation.stats;
  }, GLOW_LAYER);
  expect(dust.dust).toBe(directory().length);
  expect(dust.dustInView).toBeGreaterThan(500);
  const read = requests.map((request) => new URL(request.url).pathname);
  expect(read.some((file) => file.includes('/data/schools/points.'))).toBe(true);

  // Across the metro, every school the directory puts in view has its dot, and its light, and
  // none its name yet.
  await page.goto(`${site}?at=39.03,-94.58,10.2`);
  await settle(page);
  const inView = await schoolsInView(page);
  expect(inView.size).toBeGreaterThan(500);
  const metro = new Set((await drawn(page, BASEMAP_IDS.schoolDots)).map(({ id }) => id));
  expect([...inView].filter((id) => !metro.has(id))).toEqual([]);
  // A dot whose school stands just past the edge still shows its edge on the screen.
  expect(metro.size - inView.size).toBeLessThan(inView.size / 100);
  const lit = new Set((await drawn(page, BASEMAP_IDS.schoolLight)).map(({ id }) => id));
  expect([...inView].filter((id) => !lit.has(id))).toEqual([]);
  expect(await drawn(page, BASEMAP_IDS.schoolNames)).toEqual([]);
  // Each dot's feature id is its school's place in the directory, as in the glow's own data: the
  // glow takes the dot of each school it lights off the map by it (glow-mount.ts).
  const places = new Map(directory().map(({ id }, index) => [id, index]));
  const features = await page.evaluate(
    (layer) =>
      window.snowlightMap
        ?.queryRenderedFeatures({ layers: [layer] })
        .map((feature) => [String(feature.properties.id), feature.id] as const) ?? [],
    BASEMAP_IDS.schoolDots,
  );
  expect(features.length).toBeGreaterThan(500);
  expect(features.filter(([id, feature]) => places.get(id) !== feature)).toEqual([]);

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
  // A school the directory names only by its level carries its charter's name first; one it cut
  // off mid-word ends with the word its district's other schools show it can only be.
  const shown = new Map([...named, ...dots].map(({ id, name }) => [id, name] as const));
  expect(shown.get(CITIZENS_ELEMENTARY)).toBe('Citizens of the World Charter - Elementary School');
  expect(shown.get(ALLEN_VILLAGE_ELEMENTARY)).toBe('Allen Village Elementary Academy');
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

test('no label runs under the search field, the legend or any control, or off the screen, from zoom 13 to 15', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  // The Plaza and Allen Village, where the judges saw names cut by the field and printed through
  // the legend, at a desktop's size and a phone's.
  const VIEWS = [
    [39.045, -94.595, 13.2],
    [39.052, -94.596, 14],
    [39.0535, -94.5955, 15],
    [39.0362, -94.593, 15.2],
    [39.06, -94.58, 13],
    [39.04, -94.6, 14.5],
  ] as const;
  const SCREENS = [
    { width: 1440, height: 900, deviceScaleFactor: 1, isMobile: false },
    { width: 390, height: 844, deviceScaleFactor: 3, isMobile: true },
  ];
  const found: string[] = [];
  for (const screen of SCREENS) {
    const context = await browser.newContext({
      viewport: { width: screen.width, height: screen.height },
      deviceScaleFactor: screen.deviceScaleFactor,
      isMobile: screen.isMobile,
      hasTouch: screen.isMobile,
    });
    const page = await context.newPage();
    const { problems } = watch(page);
    let schools = 0;
    let streets = 0;
    for (const [lat, lon, zoom] of VIEWS) {
      const where = `${String(screen.width)}x${String(screen.height)} at ${String(lat)},${String(lon)},${String(zoom)}`;
      await page.goto(`${site}?at=${String(lat)},${String(lon)},${String(zoom)}`);
      await settle(page);
      const result = await page.evaluate(
        ({ space, schoolNames, streetNames }) => {
          const map = window.snowlightMap;
          if (map === undefined) throw new Error('no map');
          const labels = map
            .getLayersOrder()
            .filter((id) => map.getLayer(id)?.type === 'symbol' && id !== space);
          const canvas = map.getCanvas().getBoundingClientRect();
          const controls = [
            ...document.querySelectorAll(
              '.wordmark, .search, .updated, .legend, .locate, .maplibregl-ctrl',
            ),
          ]
            .map((element) => ({
              name: (element.getAttribute('class') ?? '').split(' ')[0] ?? '',
              rect: element.getBoundingClientRect(),
            }))
            .filter(({ rect }) => rect.width > 0 && rect.height > 0);
          const { width, height } = canvas;
          // A pixel's strip along each edge of the screen: a label that crosses one is cut.
          const edges = [
            { name: 'left edge', rect: new DOMRect(0, 0, 1, height) },
            { name: 'right edge', rect: new DOMRect(width - 1, 0, 1, height) },
            { name: 'top edge', rect: new DOMRect(0, 0, width, 1) },
            { name: 'bottom edge', rect: new DOMRect(0, height - 1, width, 1) },
          ];
          const under = [...controls, ...edges].flatMap(({ name, rect }) =>
            map
              .queryRenderedFeatures(
                [
                  [rect.left - canvas.left, rect.top - canvas.top],
                  [rect.right - canvas.left, rect.bottom - canvas.top],
                ],
                { layers: labels },
              )
              .map(
                (feature) =>
                  `${feature.layer.id} "${String(feature.properties.name ?? feature.properties.label)}" under ${name}`,
              ),
          );
          const count = (id: string): number =>
            map.getLayer(id) === undefined ? 0 : map.queryRenderedFeatures({ layers: [id] }).length;
          return {
            under,
            controls: controls.map(({ name }) => name),
            schools: count(schoolNames),
            streets: count(streetNames),
          };
        },
        {
          space: BASEMAP_IDS.schoolSpace,
          schoolNames: BASEMAP_IDS.schoolNames,
          streetNames: BASEMAP_IDS.ofmStreetLabel,
        },
      );
      // The controls were there to keep clear of.
      expect(result.controls, where).toEqual(
        expect.arrayContaining(['wordmark', 'search', 'legend', 'maplibregl-ctrl']),
      );
      schools += result.schools;
      streets += result.streets;
      found.push(...result.under.map((label) => `${where}: ${label}`));
    }
    // And names were drawn around them, schools' and streets'.
    expect(schools).toBeGreaterThan(VIEWS.length);
    expect(streets).toBeGreaterThan(5 * VIEWS.length);
    expect(problems).toEqual([]);
    await context.close();
  }
  expect(found).toEqual([]);
});

/**
 * How far apart a hand's presses and releases come in a quick double click or double tap, in
 * seconds. The tests stamp each with its time, so the page hears them as a hand makes them:
 * one after another, awaited, they can come a second apart on a busy machine, as two single
 * clicks.
 */
const HAND_S = 0.07;

/** Pembroke Hill among its neighbours at zoom 14, its dot drawn and its name beside it. */
const AT_PEMBROKE_HILL = `${String(PEMBROKE_HILL.lat)},${String(PEMBROKE_HILL.lon)},14`;

test('a school’s dot takes a click and opens as a search pick does; a drag opens nothing, a double click opens it once', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  const panel = page.locator('aside.detail');
  /** A while after a click or a gesture: no school's panel, and no school in the address. */
  const openedNothing = async (): Promise<void> => {
    await page.waitForTimeout(1500);
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
  };
  /** Where the map lands for Pembroke Hill: the view in the address, and the school on the screen. */
  const landing = async (): Promise<number[]> => {
    await expectLandedBesidePanel(page);
    await settle(page);
    const at = (new URL(page.url()).searchParams.get('at') ?? '').split(',').map(Number);
    const where = await schoolOnScreen(page);
    return [...at, where.x, where.y];
  };

  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  let dot = await schoolOnScreen(page);
  // A pointer over the dot, and the map's own cursor off it.
  expect(await nearestOtherSchool(page, dot.x, dot.y)).toBeGreaterThan(40);
  await page.mouse.move(dot.x + 3, dot.y - 2);
  await expect.poll(() => mapCursor(page)).toBe('pointer');
  await page.mouse.move(dot.x - 40, dot.y - 40);
  await expect.poll(() => mapCursor(page)).toBe('grab');

  // A drag across the dot, and one from it: the map moves, and nothing opens.
  await page.mouse.move(dot.x - 60, dot.y);
  await page.mouse.down();
  await page.mouse.move(dot.x + 60, dot.y, { steps: 12 });
  await page.mouse.up();
  await openedNothing();
  dot = await schoolOnScreen(page);
  await page.mouse.move(dot.x, dot.y);
  await page.mouse.down();
  await page.mouse.move(dot.x + 80, dot.y + 40, { steps: 12 });
  await page.mouse.up();
  await openedNothing();

  const mouse = await context.newCDPSession(page);
  /** A double click, its presses and releases a hand's time apart, stamped so the page hears it. */
  const doubleClick = async (at: { x: number; y: number }): Promise<void> => {
    const presses = ['mousePressed', 'mouseReleased', 'mousePressed', 'mouseReleased'] as const;
    const clickedAt = Date.now() / 1000 - 1;
    await Promise.all(
      presses.map((type, i) =>
        mouse.send('Input.dispatchMouseEvent', {
          type,
          x: at.x,
          y: at.y,
          button: 'left',
          buttons: type === 'mousePressed' ? 1 : 0,
          clickCount: i < 2 ? 1 : 2,
          timestamp: clickedAt + i * HAND_S,
        }),
      ),
    );
  };

  // A double click where no school is: the map zooms in a level, and nothing opens.
  await settle(page);
  const clear = await clearSpot(page);
  await doubleClick(clear);
  await expect.poll(async () => (await mapView(page)).zoom, { timeout: 30_000 }).toBeCloseTo(15, 1);
  await openedNothing();

  // A double click on the dot opens its school, once: the first click opens it at once, and the
  // second keeps the pick's flight going rather than zooming about the dot. It lands the school
  // beside its panel, as a pick does, one step on.
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  dot = await schoolOnScreen(page);
  const unopened = new URL(page.url()).searchParams.get('at');
  // Once the taps' code is in, as the cursor says: a double click before it zooms the map, which
  // drops the click kept for it.
  await page.mouse.move(dot.x, dot.y);
  await expect.poll(() => mapCursor(page)).toBe('pointer');
  await doubleClick(dot);
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus', {
    timeout: 30_000,
  });
  await expectLandedBesidePanel(page);
  await page.goBack();
  await expect(panel).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('at')).toBe(unopened);

  // A click on the dot, from zoom 14: the school's panel, its address and the pick's camera.
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  dot = await schoolOnScreen(page);
  const before = new URL(page.url()).searchParams.get('at');
  await page.mouse.click(dot.x + 2, dot.y + 2);
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus', {
    timeout: 30_000,
  });
  await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);
  await expect(page.locator('input.search-input')).toHaveValue(PEMBROKE_HILL_NAME);
  await expect(panel).toBeFocused();
  const clicked = await landing();
  expect(
    await page.evaluate(
      (id) => window.snowlightMap?.getFilter(id) as unknown,
      BASEMAP_IDS.schoolSelected,
    ),
  ).toEqual(['==', ['get', 'id'], PEMBROKE_HILL.id]);

  // A click where no school is leaves the panel open.
  const empty = await clearSpot(page);
  await page.mouse.click(empty.x, empty.y);
  await page.waitForTimeout(1500);
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
  expect(new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);
  // The click was a step of its own: Back goes to the view before it.
  await page.goBack();
  await expect(panel).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('at')).toBe(before);

  // Picked in search from that same view, the school lands as the click took it: the same panel,
  // the same address, and the same camera, as near as the search index's places go. It keeps
  // them to 4 decimals (search/format.ts), about 10 m: a few pixels here, and the address's last
  // decimal.
  await settle(page);
  const input = page.locator('input.search-input');
  await input.fill('');
  await input.pressSequentially('pembroke', { delay: 20 });
  await page.locator('[role="option"]', { hasText: PEMBROKE_HILL_NAME }).click();
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
  await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);
  await expect(panel).toBeFocused();
  const picked = await landing();
  expect(clicked).toHaveLength(5);
  expect(clicked[2]).toBe(15);
  // Latitude, longitude and zoom in the address, then the school's place on the screen.
  const near = [1e-4, 1e-4, 0, 4, 4];
  clicked.forEach((value, i) => {
    expect(Math.abs(value - (picked[i] ?? Number.NaN))).toBeLessThanOrEqual(near[i] ?? 0);
  });
  expect(problems).toEqual([]);
  await context.close();
});

test('on a phone a tap a little off a dot opens it; a drag, a pinch or a double tap opens nothing', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const context = await browser.newContext({ ...devices['Pixel 7'] });
  const page = await context.newPage();
  const { problems } = watch(page);
  const touch = await context.newCDPSession(page);
  const sheet = page.locator('aside.detail');
  interface Finger {
    x: number;
    y: number;
  }
  /**
   * Fingers put down at `from`, moved to `to` over `ms`, and lifted: sent at once, each event
   * stamped with its time, as for the double tap below.
   */
  const gesture = async (from: Finger[], to: Finger[], ms: number): Promise<void> => {
    const steps = ms > 0 ? Math.max(1, Math.round(ms / 16)) : 0;
    const start = Date.now() / 1000 - 1;
    const moves = Array.from({ length: steps }, (_, n) => ({
      type: 'touchMove' as const,
      touchPoints: from.map((finger, i) => ({
        x: finger.x + (((to[i] ?? finger).x - finger.x) * (n + 1)) / steps,
        y: finger.y + (((to[i] ?? finger).y - finger.y) * (n + 1)) / steps,
      })),
    }));
    const events = [
      { type: 'touchStart' as const, touchPoints: from },
      ...moves,
      { type: 'touchEnd' as const, touchPoints: [] },
    ];
    await Promise.all(
      events.map((event, n) =>
        touch.send('Input.dispatchTouchEvent', { ...event, timestamp: start + n * 0.016 }),
      ),
    );
  };
  const openedNothing = async (): Promise<void> => {
    await page.waitForTimeout(1500);
    await expect(sheet).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
  };

  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  let dot = await schoolOnScreen(page);
  // A finger dragged across the dot.
  await gesture([{ x: dot.x - 60, y: dot.y }], [{ x: dot.x + 60, y: dot.y }], 300);
  await openedNothing();
  // Two fingers pinched out over it.
  await settle(page);
  dot = await schoolOnScreen(page);
  await gesture(
    [
      { x: dot.x - 20, y: dot.y },
      { x: dot.x + 20, y: dot.y },
    ],
    [
      { x: dot.x - 90, y: dot.y },
      { x: dot.x + 90, y: dot.y },
    ],
    300,
  );
  await openedNothing();
  // Two fingers tapped on it: MapLibre zooms out.
  await settle(page);
  dot = await schoolOnScreen(page);
  const zoom = (await mapView(page)).zoom;
  await gesture(
    [
      { x: dot.x - 8, y: dot.y },
      { x: dot.x + 8, y: dot.y },
    ],
    [],
    0,
  );
  await expect
    .poll(async () => (await mapView(page)).zoom, { timeout: 30_000 })
    .toBeLessThan(zoom - 0.5);
  await openedNothing();
  // A tap 14 px from the dot's center, about 9 px from its edge, past a mouse's reach and within
  // a finger's: once no second tap follows, the school's sheet, its address, and the school in
  // the middle of the map above the sheet, as a pick puts it. In real time: the double tap below
  // holds the page's clock, which would stretch this flight.
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  dot = await schoolOnScreen(page);
  const offDot = { x: dot.x + 11, y: dot.y + 9 };
  expect(await nearestOtherSchool(page, offDot.x, offDot.y)).toBeGreaterThan(40);
  await page.touchscreen.tap(offDot.x, offDot.y);
  await expect(sheet.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus', {
    timeout: 30_000,
  });
  await expect(sheet).toHaveAttribute('data-detent', 'open');
  await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);
  const { width, height } = page.viewportSize() ?? { width: 0, height: 0 };
  const barBottom = await page
    .locator('.bar')
    .evaluate((bar) => bar.getBoundingClientRect().bottom);
  const opensAt = height - Math.round(height / 2);
  await expect
    .poll(
      async () => {
        const view = await mapView(page);
        const where = await schoolOnScreen(page);
        return (
          Math.abs(view.zoom - 15) < 0.05 &&
          Math.abs(where.x - width / 2) < 4 &&
          Math.abs(where.y - (barBottom + opensAt) / 2) < 4
        );
      },
      { timeout: 60_000 },
    )
    .toBe(true);

  // Last, a double tap on it zooms in a level. Each tap is sent once the page has heard the one
  // before, stamped a hand's time after it, and the page's clock holds still from the first tap
  // to the second: however late a busy machine sends the second, the page hears a double tap.
  await page.clock.install();
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  dot = await schoolOnScreen(page);
  await page.clock.pauseAt(Date.now() + 500);
  const tappedAt = Date.now() / 1000;
  // The first tap is heard with its click; the second, a double tap's with none, as it ends.
  for (const [tap, heard] of [
    [0, 'click'],
    [1, 'touchend'],
  ] as const) {
    await page.evaluate((type) => {
      (window as unknown as { tapHeard?: Promise<void> }).tapHeard = new Promise((resolve) => {
        window.addEventListener(
          type,
          () => {
            resolve();
          },
          { once: true, capture: true },
        );
      });
    }, heard);
    for (const type of ['touchStart', 'touchEnd'] as const) {
      await touch.send('Input.dispatchTouchEvent', {
        type,
        touchPoints: type === 'touchStart' ? [{ x: dot.x, y: dot.y }] : [],
        timestamp: tappedAt + (tap * 2 + (type === 'touchEnd' ? 1 : 0)) * HAND_S,
      });
    }
    await page.evaluate(() => (window as unknown as { tapHeard?: Promise<void> }).tapHeard);
  }
  await page.clock.resume();
  await expect.poll(async () => (await mapView(page)).zoom, { timeout: 30_000 }).toBeCloseTo(15, 1);
  await openedNothing();
  expect(problems).toEqual([]);
  await context.close();
});

test('a click heard before the taps’ code is in opens the school clicked, and none once the map moved', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  // No service worker: it would serve the taps' code from its cache, past the hold below.
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    serviceWorkers: 'block',
  });
  const page = await context.newPage();
  const { problems } = watch(page);
  const panel = page.locator('aside.detail');
  // The taps' code held back: the next page's download of it, until it is let go.
  const TAPS_CODE = /\/assets\/school-taps-[^/]+\.js$/;
  let next: { asked: () => void; gate: Promise<void> } | null = null;
  const held = (): { asked: Promise<void>; letGo: () => void } => {
    let asked: () => void = () => undefined;
    let letGo: () => void = () => undefined;
    const heard = new Promise<void>((resolve) => {
      asked = resolve;
    });
    const gate = new Promise<void>((resolve) => {
      letGo = resolve;
    });
    next = { asked, gate };
    return { asked: heard, letGo };
  };
  await page.route(TAPS_CODE, async (route) => {
    const hold = next;
    next = null;
    if (hold !== null) {
      hold.asked();
      await hold.gate;
    }
    await route.continue();
  });

  // On a map that has not moved since, the click opens the school it fell on.
  let code = held();
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  await code.asked;
  let dot = await schoolOnScreen(page);
  await page.mouse.click(dot.x + 1, dot.y + 1);
  await page.waitForTimeout(1000);
  await expect(panel).toHaveCount(0);
  code.letGo();
  await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus', {
    timeout: 30_000,
  });
  expect(new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL.id);

  // Clicked on Pembroke Hill's dot, and the map dragged until St Teresa's Academy is where the
  // click fell: that point is another school now, and the click opens nothing.
  code = held();
  await page.goto(`${site}?at=${AT_PEMBROKE_HILL}`);
  await settle(page);
  await code.asked;
  dot = await schoolOnScreen(page);
  const clicked = { x: dot.x + 1, y: dot.y + 1 };
  await page.mouse.click(clicked.x, clicked.y);
  const teresa = await page.evaluate(
    ({ layers }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const box = map.getContainer().getBoundingClientRect();
      const found = map
        .queryRenderedFeatures({ layers })
        .find((feature) => String(feature.properties.name).startsWith('St Teresa'));
      if (found === undefined) throw new Error('no St Teresa’s Academy on the map');
      const [lon, lat] = (found.geometry as { coordinates: [number, number] }).coordinates;
      const at = map.project([lon, lat]);
      return { id: String(found.properties.id), lon, lat, x: box.left + at.x, y: box.top + at.y };
    },
    { layers: [BASEMAP_IDS.schoolDots] },
  );
  // Dragged from a point clear of every school, the whole drag on the map.
  const drag = { x: clicked.x - teresa.x, y: clicked.y - teresa.y };
  const grab = await clearSpot(page, drag);
  await page.mouse.move(grab.x, grab.y);
  await page.mouse.down();
  await page.mouse.move(grab.x + drag.x, grab.y + drag.y, { steps: 12 });
  await page.mouse.up();
  await settle(page);
  const moved = await page.evaluate(({ lon, lat }) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const box = map.getContainer().getBoundingClientRect();
    const at = map.project([lon, lat]);
    return { x: box.left + at.x, y: box.top + at.y };
  }, teresa);
  expect(Math.hypot(moved.x - clicked.x, moved.y - clicked.y)).toBeLessThan(4);
  code.letGo();
  await page.waitForTimeout(2000);
  await expect(panel).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('school')).toBeNull();
  // The taps are in: over St Teresa's Academy now, the cursor says a click would open it.
  await page.mouse.move(clicked.x, clicked.y);
  await expect.poll(() => mapCursor(page)).toBe('pointer');
  // Playwright says so when it blocks the service worker; nothing else is said.
  expect(problems.filter((problem) => !problem.includes('Service Worker'))).toEqual([]);
  await context.close();
});

test('specks too faint to be half drawn take no click; from where they are, a click on one opens its school', async ({
  browser,
}) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const { problems } = watch(page);
  const panel = page.locator('aside.detail');
  const schools = directory();
  /**
   * Once the glow layer draws the dust, a school whose speck is near the middle of the map,
   * clear of every other school's: its id, and where it is on the page.
   */
  const aSpeck = async (): Promise<{ id: string; x: number; y: number }> => {
    await page.waitForFunction(
      (id) => {
        const layer = window.snowlightMap?.getLayer(id) as unknown as
          { implementation: { stats: { dust: number; dustDrawn: boolean } } } | undefined;
        const stats = layer?.implementation.stats;
        return stats !== undefined && stats.dust > 0 && stats.dustDrawn;
      },
      GLOW_LAYER,
      { timeout: 60_000 },
    );
    const view = await page.evaluate(() => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const bounds = map.getBounds();
      return {
        west: bounds.getWest() - 1,
        east: bounds.getEast() + 1,
        south: bounds.getSouth() - 1,
        north: bounds.getNorth() + 1,
      };
    });
    const near = schools.filter(
      ({ lon, lat }) => lon > view.west && lon < view.east && lat > view.south && lat < view.north,
    );
    return page.evaluate(
      ({ near }) => {
        const map = window.snowlightMap;
        if (map === undefined) throw new Error('no map');
        const box = map.getContainer().getBoundingClientRect();
        const specks = near.map((school) => {
          const { x, y } = map.project([school.lon, school.lat]);
          return { id: school.id, x, y };
        });
        const alone = specks.filter(
          (speck) =>
            speck.x > 0 &&
            speck.x < box.width &&
            speck.y > 0 &&
            speck.y < box.height &&
            specks.every(
              (other) => other === speck || Math.hypot(other.x - speck.x, other.y - speck.y) > 40,
            ),
        );
        const middle = { x: box.width / 2 + 200, y: box.height / 2 };
        alone.sort(
          (a, b) =>
            Math.hypot(a.x - middle.x, a.y - middle.y) - Math.hypot(b.x - middle.x, b.y - middle.y),
        );
        const speck = alone[0];
        if (speck === undefined) throw new Error('no speck alone');
        return { id: speck.id, x: box.left + speck.x, y: box.top + speck.y };
      },
      { near },
    );
  };

  // Kansas at zoom 7.5: every school a faint speck, under half drawn (dots.ts). A click on one
  // is a click on the map, and the cursor stays the map's.
  await page.goto(`${site}?at=39.2,-95.9,7.5`);
  await settle(page);
  const faint = await aSpeck();
  await page.mouse.move(faint.x, faint.y);
  await page.waitForTimeout(500);
  expect(await mapCursor(page)).toBe('grab');
  await page.mouse.click(faint.x, faint.y);
  await page.waitForTimeout(1500);
  await expect(panel).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('school')).toBeNull();
  expect((await mapView(page)).zoom).toBeCloseTo(7.5, 2);

  // At zoom 8.2 the specks are more than half drawn: one takes the pointer, and a click on it
  // opens its school, as a click on its dot does closer in.
  await page.goto(`${site}?at=39.2,-95.9,8.2`);
  await settle(page);
  const speck = await aSpeck();
  await page.mouse.move(speck.x, speck.y);
  await expect.poll(() => mapCursor(page)).toBe('pointer');
  await page.mouse.click(speck.x, speck.y);
  await expect
    .poll(() => new URL(page.url()).searchParams.get('school'), { timeout: 30_000 })
    .toBe(speck.id);
  await expect(panel).toHaveCount(1);
  expect(problems).toEqual([]);
  await context.close();
});

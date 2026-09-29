/**
 * The map shows the continental US only. At the border with Canada (Detroit
 * and Windsor) and with Mexico (San Diego and Tijuana), MapLibre has no road
 * or name on the foreign side to draw, place or query, and the US side keeps
 * its roads. The mask the street tiles are cut with is read from the site,
 * whole and once, only once street tiles are needed (zoom 7 and up), never
 * on a plain visit.
 *
 * The checks read what MapLibre drew (queryRenderedFeatures) through the
 * handle the page sets under automation, window.snowlightMap. Street tiles
 * come from tiles.openfreemap.org, so these tests need the network.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { Map as MapLibreMap } from 'maplibre-gl';

import { BASEMAP_IDS } from '../src/map/basemap/ids';

declare global {
  interface Window {
    snowlightMap?: MapLibreMap;
  }
}

/** Chrome's own GPU driver chatter under software WebGL, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

/** The mask archive, under geo/ on the site. */
const MASK_FILE = /\/geo\/us-mask\.[0-9a-f]+\.pmtiles$/;

const ROADS = [
  BASEMAP_IDS.ofmRoad,
  BASEMAP_IDS.ofmRoadTunnel,
  BASEMAP_IDS.ofmBridge,
  BASEMAP_IDS.ofmBridgeCasing,
];
const LABELS = [
  BASEMAP_IDS.ofmNeighbourhoodLabel,
  BASEMAP_IDS.ofmStreetLabel,
  BASEMAP_IDS.ofmMajorRoadLabel,
  BASEMAP_IDS.ofmWaterLabel,
  BASEMAP_IDS.ofmParkLabel,
  BASEMAP_IDS.ofmVillageLabel,
  BASEMAP_IDS.ofmTownLabel,
  BASEMAP_IDS.ofmCityLabel,
];

/** West, south, east, north in degrees. */
type Box = readonly [number, number, number, number];

// Software WebGL and tiles from the network.
test.describe.configure({ timeout: 120_000 });

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

/** Opens a view from a link and waits until every tile is in and the map is at rest. */
async function openView(page: Page, lat: number, lon: number, zoom: number): Promise<void> {
  await page.goto(`/?at=${String(lat)},${String(lon)},${String(zoom)}`);
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout: 90_000, polling: 250 },
  );
  // One more full frame: labels are placed on the frame after their tiles arrive.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const map = window.snowlightMap;
        if (map === undefined) {
          resolve();
          return;
        }
        map.once('idle', () => {
          resolve();
        });
        map.triggerRepaint();
      }),
  );
}

interface Found {
  /** Features of the layers drawn over the part of the box on screen. */
  readonly count: number;
  /** Names among them. */
  readonly names: string[];
  /** Screen area of the box, in CSS pixels. */
  readonly area: number;
}

/** What MapLibre drew of the given layers over a box, cut to the screen. */
async function drawnIn(page: Page, box: Box, layers: readonly string[]): Promise<Found> {
  return page.evaluate(
    ({ box: [west, south, east, north], layers: ids }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const a = map.project([west, north]);
      const b = map.project([east, south]);
      const canvas = map.getCanvas();
      const x0 = Math.max(0, Math.min(a.x, b.x));
      const x1 = Math.min(canvas.clientWidth, Math.max(a.x, b.x));
      const y0 = Math.max(0, Math.min(a.y, b.y));
      const y1 = Math.min(canvas.clientHeight, Math.max(a.y, b.y));
      if (x1 - x0 < 1 || y1 - y0 < 1) return { count: 0, names: [], area: 0 };
      const features = map.queryRenderedFeatures(
        [
          [x0, y0],
          [x1, y1],
        ],
        { layers: ids.filter((id) => map.getLayer(id) !== undefined) },
      );
      const names = features.flatMap((feature) => {
        const name: unknown = (feature.properties as Record<string, unknown>).name;
        return typeof name === 'string' ? [name] : [];
      });
      return { count: features.length, names, area: (x1 - x0) * (y1 - y0) };
    },
    { box, layers },
  );
}

/** Names placed anywhere on screen. */
async function namesOnScreen(page: Page): Promise<string[]> {
  return page.evaluate(
    (ids) =>
      (window.snowlightMap?.queryRenderedFeatures({ layers: ids }) ?? []).flatMap((feature) => {
        const name: unknown = (feature.properties as Record<string, unknown>).name;
        return typeof name === 'string' ? [name] : [];
      }),
    LABELS,
  );
}

test('below zoom 7 the mask is not asked for', async ({ page }) => {
  const problems = watch(page);
  const masks: string[] = [];
  page.on('request', (request) => {
    if (MASK_FILE.test(new URL(request.url()).pathname)) masks.push(request.url());
  });
  await openView(page, 42.32, -83.05, 6.5);
  await page.waitForTimeout(1_000);
  expect(masks).toEqual([]);
  expect(problems).toEqual([]);
});

test('a plain visit, at the national view, never asks for the mask', async ({ page }) => {
  const problems = watch(page);
  const masks: string[] = [];
  page.on('request', (request) => {
    if (/\/geo\/us-mask\b/.test(new URL(request.url()).pathname)) masks.push(request.url());
  });
  await page.goto('/');
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout: 90_000, polling: 250 },
  );
  await page.waitForTimeout(2_000);
  expect(masks).toEqual([]);
  expect(problems).toEqual([]);
});

test('Detroit keeps its roads and names; Windsor across the river has none', async ({ page }) => {
  const problems = watch(page);
  const masks: { url: string; range: string | null }[] = [];
  page.on('request', (request) => {
    if (/\/geo\/us-mask\b/.test(new URL(request.url()).pathname)) {
      masks.push({ url: request.url(), range: request.headers().range ?? null });
    }
  });
  await openView(page, 42.32, -83.05, 13);
  // Windsor, from its riverfront south: Canada, well clear of the border in the river.
  const windsor: Box = [-83.055, 42.3, -83.03, 42.312];
  // Downtown Detroit.
  const detroit: Box = [-83.06, 42.328, -83.04, 42.34];
  const foreignRoads = await drawnIn(page, windsor, ROADS);
  const foreignNames = await drawnIn(page, windsor, LABELS);
  expect(foreignRoads.area).toBeGreaterThan(5_000);
  expect(foreignRoads.count).toBe(0);
  expect(foreignNames.count).toBe(0);
  const usRoads = await drawnIn(page, detroit, ROADS);
  expect(usRoads.count).toBeGreaterThan(50);
  const names = await namesOnScreen(page);
  expect(names).toContain('Detroit');
  expect(names).not.toContain('Windsor');
  // The mask came from the site once, whole: a range of it can come back as a range of its gzip.
  expect(masks).toHaveLength(1);
  expect(masks[0]?.url).toMatch(MASK_FILE);
  expect(masks[0]?.range).toBeNull();
  expect(problems).toEqual([]);
});

test('San Diego keeps its roads; Tijuana across the border has none', async ({ page }) => {
  const problems = watch(page);
  await openView(page, 32.55, -117.05, 12);
  // Tijuana, south of the border fence.
  const tijuana: Box = [-117.06, 32.505, -117.01, 32.525];
  // San Ysidro and Otay Mesa West.
  const sanYsidro: Box = [-117.06, 32.55, -117.02, 32.57];
  const foreignRoads = await drawnIn(page, tijuana, ROADS);
  const foreignNames = await drawnIn(page, tijuana, LABELS);
  expect(foreignRoads.area).toBeGreaterThan(5_000);
  expect(foreignRoads.count).toBe(0);
  expect(foreignNames.count).toBe(0);
  const usRoads = await drawnIn(page, sanYsidro, ROADS);
  expect(usRoads.count).toBeGreaterThan(20);
  const names = await namesOnScreen(page);
  expect(names).toContain('San Ysidro');
  expect(names).not.toContain('Tijuana');
  expect(problems).toEqual([]);
});

/** Canada across the river from Detroit, well clear of the border: land and lake. */
const ONTARIO: readonly { readonly name: string; readonly box: Box }[] = [
  // Windsor south to Essex County, all land.
  { name: 'Windsor and Essex County', box: [-83.04, 42.1, -82.55, 42.28] },
  // Lake St. Clair's Canadian part and its south shore.
  { name: 'Lake St. Clair', box: [-82.75, 42.33, -82.45, 42.42] },
];

/**
 * Zooms from one zoom to another over `seconds`, reading every frame drawn,
 * streets loading and all, with nothing but the areas and lines under the
 * mask shown (no labels, border line, schools or glow): for each box, the
 * brightest pixel of each frame over it.
 */
async function framesOver(
  page: Page,
  boxes: readonly Box[],
  toZoom: number,
  seconds: number,
): Promise<{ zoom: number; brightest: number[]; masked: (boolean | null)[] }[]> {
  return page.evaluate(
    async ({ boxes: areas, toZoom: zoom, seconds: duration }) => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      for (const id of map.getLayersOrder()) {
        const type = map.getLayer(id)?.type;
        if (
          type === 'symbol' ||
          type === 'custom' ||
          id === 'us-border' ||
          id.startsWith('school')
        ) {
          map.setLayoutProperty(id, 'visibility', 'none');
        }
      }
      const canvas = map.getCanvas();
      const gl = canvas.getContext('webgl2');
      if (gl === null) throw new Error('no WebGL 2');
      const frames: { zoom: number; brightest: number[]; masked: (boolean | null)[] }[] = [];
      const read = (): void => {
        const width = gl.drawingBufferWidth;
        const height = gl.drawingBufferHeight;
        const ratio = width / canvas.clientWidth;
        const row = new Uint8Array(width * 4);
        const brightest = areas.map(([west, south, east, north]) => {
          const a = map.project([west, north]);
          const b = map.project([east, south]);
          const x0 = Math.max(0, Math.ceil(a.x));
          const x1 = Math.min(canvas.clientWidth - 1, Math.floor(b.x));
          const y0 = Math.max(0, Math.ceil(a.y));
          const y1 = Math.min(canvas.clientHeight - 1, Math.floor(b.y));
          let most = x1 >= x0 && y1 >= y0 ? 0 : -1;
          for (let y = y0; y <= y1; y += 2) {
            gl.readPixels(
              0,
              height - 1 - Math.round(y * ratio),
              width,
              1,
              gl.RGBA,
              gl.UNSIGNED_BYTE,
              row,
            );
            for (let x = x0; x <= x1; x += 2) {
              const i = Math.round(x * ratio) * 4;
              most = Math.max(most, row[i] ?? 0, row[i + 1] ?? 0, row[i + 2] ?? 0);
            }
          }
          return most;
        });
        // Whether the mask is there, under the middle of each box's part on screen (null for none).
        const masked = areas.map(([west, south, east, north]) => {
          const a = map.project([west, north]);
          const b = map.project([east, south]);
          const x0 = Math.max(0, a.x);
          const x1 = Math.min(canvas.clientWidth, b.x);
          const y0 = Math.max(0, a.y);
          const y1 = Math.min(canvas.clientHeight, b.y);
          if (x1 - x0 < 4 || y1 - y0 < 4) return null;
          const middle: [number, number] = [(x0 + x1) / 2, (y0 + y1) / 2];
          return map.queryRenderedFeatures(middle, { layers: ['us-mask'] }).length > 0;
        });
        frames.push({ zoom: map.getZoom(), brightest, masked });
      };
      map.on('render', read);
      await new Promise<void>((resolve) => {
        map.once('idle', () => {
          resolve();
        });
        map.triggerRepaint();
      });
      map.easeTo({ zoom, duration: duration * 1000 });
      await new Promise<void>((resolve) => {
        map.once('moveend', () => {
          resolve();
        });
      });
      await new Promise<void>((resolve) => {
        map.once('idle', () => {
          resolve();
        });
        map.triggerRepaint();
      });
      map.off('render', read);
      return frames;
    },
    { boxes, toZoom, seconds },
  );
}

for (const [place, lat, lon] of [
  // Detroit's east side, with the lake in view on a phone too; Windsor, across the river.
  ['Detroit', 42.35, -82.98],
  ['Windsor', 42.26, -82.9],
] as const) {
  test(`nothing of Canada shows past the mask from ${place}, zoom 9 to 11 and back, every frame`, async ({
    page,
  }) => {
    const problems = watch(page);
    await openView(page, lat, lon, 9);
    const boxes = ONTARIO.map(({ box }) => box);
    const frames = [
      ...(await framesOver(page, boxes, 10, 1.5)),
      ...(await framesOver(page, boxes, 11, 1.5)),
      ...(await framesOver(page, boxes, 9, 2)),
    ];
    expect(frames.length).toBeGreaterThan(20);
    // Every zoom from 9 to 11 was drawn, settled ones included.
    for (const zoom of [9, 10, 11]) {
      expect(frames.some((frame) => Math.abs(frame.zoom - zoom) < 0.01)).toBe(true);
    }
    // Windsor is on screen at every zoom; the lake, from where it is.
    expect(frames.filter((frame) => (frame.brightest[0] ?? -1) >= 0).length).toBeGreaterThan(5);
    ONTARIO.forEach(({ name }, i) => {
      const drawn = frames.filter((frame) => (frame.brightest[i] ?? -1) >= 0);
      // Black ground: no road, water, park or tile edge of Canada in any frame.
      const lit = drawn.filter((frame) => (frame.brightest[i] ?? 0) > 2);
      expect(
        lit.map((frame) => `${frame.zoom.toFixed(2)}: ${String(frame.brightest[i])}`),
        name,
      ).toEqual([]);
      // Black because the mask covers it once the streets are in, not only because they are not.
      const settled = frames.filter((frame) => frame.masked[i] !== null).at(-1);
      if (i === 0 || settled !== undefined) expect(settled?.masked[i], name).toBe(true);
    });
    expect(problems).toEqual([]);
  });
}

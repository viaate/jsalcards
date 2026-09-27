/**
 * The map shows the continental US only. At the border with Canada (Detroit
 * and Windsor) and with Mexico (San Diego and Tijuana), MapLibre has no road
 * or name on the foreign side to draw, place or query, and the US side keeps
 * its roads. The mask the street tiles are cut with is read from the site,
 * only once street tiles are needed (zoom 7 and up).
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
  BASEMAP_IDS.ofmRoadShield,
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

test('Detroit keeps its roads and names; Windsor across the river has none', async ({ page }) => {
  const problems = watch(page);
  const ranges: string[] = [];
  page.on('request', (request) => {
    if (MASK_FILE.test(new URL(request.url()).pathname)) {
      ranges.push(request.headers().range ?? 'whole file');
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
  // The mask came from the site, a range at a time.
  expect(ranges.length).toBeGreaterThan(0);
  expect(ranges.every((range) => /^bytes=\d+-\d+$/.test(range))).toBe(true);
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

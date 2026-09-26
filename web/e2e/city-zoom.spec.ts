/**
 * The map up close, in Kansas City: streets, buildings and names drawn from
 * OpenFreeMap's tiles at the views someone uses to find a school, and nothing
 * asked of the network for them below zoom 7.
 *
 * The checks read what MapLibre drew (queryRenderedFeatures) through the
 * handle the page sets under automation, window.snowlightMap. Street tiles
 * come from tiles.openfreemap.org, so these tests need the network.
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { Map as MapLibreMap } from 'maplibre-gl';
import sharp from 'sharp';

import { BASEMAP_IDS } from '../src/map/basemap/ids';

declare global {
  interface Window {
    snowlightMap?: MapLibreMap;
  }
}

/** Chrome's own GPU driver chatter under software WebGL, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

/** Where tiles, and the TileJSON that points at them, come from. */
const TILES = 'https://tiles.openfreemap.org/';

/** The families fonts.ts registers for map labels. */
const LABEL_FAMILY = /^Geist Map /;

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

interface Drawn {
  /** Features drawn, by layer id. */
  counts: Record<string, number>;
  /** Names on screen, by layer id. */
  names: Record<string, string[]>;
}

/** What the map drew on screen: features per layer and the names placed. */
async function drawn(page: Page): Promise<Drawn> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    const counts: Record<string, number> = {};
    const names: Record<string, string[]> = {};
    for (const feature of map?.queryRenderedFeatures() ?? []) {
      const id = feature.layer.id;
      counts[id] = (counts[id] ?? 0) + 1;
      const name: unknown = (feature.properties as Record<string, unknown>).name;
      if (feature.layer.type === 'symbol' && typeof name === 'string') {
        (names[id] ??= []).push(name);
      }
    }
    return { counts, names };
  });
}

/** Load status of the label faces. */
async function labelFaces(page: Page): Promise<string[]> {
  return page.evaluate(
    (family) =>
      [...document.fonts]
        .filter((face) => new RegExp(family).test(face.family))
        .map((face) => face.status),
    LABEL_FAMILY.source,
  );
}

test('below zoom 7 the map asks nothing of the network for streets or names', async ({ page }) => {
  const problems = watch(page);
  const tiles: string[] = [];
  page.on('request', (request) => {
    if (request.url().startsWith(TILES)) tiles.push(request.url());
  });
  await openView(page, 39.04, -94.59, 6.5);
  await page.waitForTimeout(1_000);
  expect(tiles).toEqual([]);
  // The label faces are registered but never loaded.
  const faces = await labelFaces(page);
  expect(faces.length).toBeGreaterThan(0);
  expect(faces.every((status) => status === 'unloaded')).toBe(true);
  expect(Object.keys((await drawn(page)).counts)).not.toContain(BASEMAP_IDS.ofmRoad);
  expect(problems).toEqual([]);
});

test('the Country Club Plaza view draws roads, buildings, water and names', async ({ page }) => {
  const problems = watch(page);
  await openView(page, 39.045, -94.595, 13.2);
  const { counts, names } = await drawn(page);
  expect(counts[BASEMAP_IDS.ofmRoad] ?? 0).toBeGreaterThan(100);
  expect(counts[BASEMAP_IDS.ofmBuilding] ?? 0).toBeGreaterThan(0);
  expect(counts[BASEMAP_IDS.ofmWaterFill] ?? 0).toBeGreaterThan(0);
  // Street names along the lines, and the names of the places around.
  expect(names[BASEMAP_IDS.ofmStreetLabel]?.length ?? 0).toBeGreaterThan(3);
  expect(names[BASEMAP_IDS.ofmMajorRoadLabel] ?? []).toContain('Ward Parkway');
  const places = [
    ...(names[BASEMAP_IDS.ofmVillageLabel] ?? []),
    ...(names[BASEMAP_IDS.ofmNeighbourhoodLabel] ?? []),
  ];
  expect(places).toContain('Country Club Plaza');
  // Every label face loaded before the first name was drawn.
  const faces = await labelFaces(page);
  expect(faces.every((status) => status === 'loaded')).toBe(true);
  expect(problems).toEqual([]);
});

test('at Pembroke Hill the streets are named and the buildings drawn', async ({ page }) => {
  const problems = watch(page);
  await openView(page, 39.0362, -94.593, 15.2);
  const { counts, names } = await drawn(page);
  expect(counts[BASEMAP_IDS.ofmBuilding] ?? 0).toBeGreaterThan(5);
  const streets = [
    ...(names[BASEMAP_IDS.ofmStreetLabel] ?? []),
    ...(names[BASEMAP_IDS.ofmMajorRoadLabel] ?? []),
  ];
  expect(streets).toContain('Wornall Road');
  expect(streets).toContain('West 51st Street');
  // On screen, not only in the tiles: a good share of the map is lit by
  // footprints, streets and names, and none of it past the palette's grey.
  const { data, info } = await sharp(await page.locator('.maplibregl-canvas').screenshot())
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  let lit = 0;
  let colored = 0;
  for (let i = 0; i < data.length; i += info.channels) {
    const [r = 0, g = 0, b = 0] = [data[i], data[i + 1], data[i + 2]];
    if (Math.max(r, g, b) > 12) lit += 1;
    if (Math.max(r, g, b) - Math.min(r, g, b) > 6) colored += 1;
  }
  const pixels = info.width * info.height;
  expect(lit / pixels).toBeGreaterThan(0.15);
  expect(colored / pixels).toBeLessThan(0.001);
  expect(problems).toEqual([]);
});

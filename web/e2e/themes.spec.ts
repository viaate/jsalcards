/**
 * Whole-app themes in the built site (src/theme/engine.ts): a theme the
 * device keeps is on from the first paint, the page and the map change
 * together at run time with no reload and no layout shift, and a theme still
 * waiting for the owner's approval (Snowball) is never put on by this build,
 * which names none in VITE_THEMES_PREVIEW.
 *
 * Runs against the default build (playwright.config.ts), which ships no data.
 */
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { Map as MapLibreMap } from 'maplibre-gl';

import { BASEMAP_IDS } from '../src/map/basemap/ids';
import { THEME_STORAGE_KEY } from '../src/theme/event';
import { THEMES } from '../src/theme/themes';
import type { ThemeId } from '../src/theme/themes';

interface Engine {
  readonly current: ThemeId;
  useTheme(id: ThemeId | null): boolean;
  previewTheme(id: ThemeId): boolean;
}

declare global {
  interface Window {
    snowlightMap?: MapLibreMap;
    snowlightTheme?: Engine;
    themeShifts?: number;
    firstGround?: string;
    /** Every frame's theme and ground, from the first. */
    themeFrames?: { theme: string | null; ground: string }[];
  }
}

test.describe.configure({ timeout: 120_000 });

/** The default build this spec runs against (playwright.config.ts builds it). */
const DIST = fileURLToPath(new URL('../dist/', import.meta.url));

test('a default build carries nothing of a theme waiting for approval, in any file', () => {
  const files = readdirSync(DIST, { recursive: true, encoding: 'utf8' }).filter(
    (file) => !/\.(?:png|jpe?g|webp|avif|ico|woff2?|pmtiles|gz|br)$/i.test(file),
  );
  expect(files.length).toBeGreaterThan(10);
  const found = files.filter((file) => {
    const full = path.join(DIST, file);
    try {
      const text = readFileSync(full, 'utf8');
      const sources = file.endsWith('.map')
        ? (JSON.parse(text) as { sources: string[] }).sources
        : [];
      return (
        /snowball|fredoka/i.test(text) ||
        /fredoka/i.test(file) ||
        sources.some((source) => source.endsWith('theme/unreleased.ts'))
      );
    } catch {
      // A directory.
      return false;
    }
  });
  // Not its colors, its face or its license, its name, nor the module that holds it (source maps
  // included).
  expect(found).toEqual([]);
});

/**
 * Keeps `id` on the device, as the engine does (or, with `extra`, as an older
 * build did), before the page loads, and records every frame from the first.
 */
async function keep(page: Page, id: ThemeId, extra: Record<string, string> = {}): Promise<void> {
  const kept = { id, ...extra };
  await page.addInitScript(
    ([key, value]) => {
      localStorage.setItem(key, value);
    },
    [THEME_STORAGE_KEY, JSON.stringify(kept)] as const,
  );
  await record(page);
}

/** Records every layout shift and every frame's theme and ground, from the first. */
async function record(page: Page): Promise<void> {
  await page.addInitScript(() => {
    // Every layout shift, from the first.
    window.themeShifts = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.themeShifts =
          (window.themeShifts ?? 0) + (entry as unknown as { value: number }).value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
    document.addEventListener('DOMContentLoaded', () => {
      window.firstGround = getComputedStyle(document.documentElement).backgroundColor;
    });
    window.themeFrames = [];
    const frame = (): void => {
      const root = document.documentElement;
      window.themeFrames?.push({
        theme: root.getAttribute('data-theme'),
        ground: getComputedStyle(document.querySelector('body') ?? root).backgroundColor,
      });
      if ((window.themeFrames?.length ?? 0) < 600) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}

async function mapReady(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      document.querySelector('svg.still') === null &&
      window.snowlightMap?.isStyleLoaded() === true &&
      window.snowlightTheme !== undefined,
    null,
    { timeout: 60_000 },
  );
}

/** The map's ground as its style has it: the color, or the sea's and the street ground's by zoom. */
async function mapGround(page: Page): Promise<string> {
  return page.evaluate(
    (id) => JSON.stringify(window.snowlightMap?.getPaintProperty(id, 'background-color') ?? null),
    BASEMAP_IDS.background,
  );
}

function rgb(hex: string): string {
  const channel = (i: number): number => Number.parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `rgb(${String(channel(0))}, ${String(channel(1))}, ${String(channel(2))})`;
}

test('a theme the device keeps is on from the first paint, page and map alike', async ({
  page,
}) => {
  await keep(page, 'daylight');
  await page.goto('/');
  await mapReady(page);
  expect(await page.evaluate(() => window.firstGround)).toBe(rgb(THEMES.daylight.tokens.bg));
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('daylight');
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('daylight');
  await expect.poll(() => mapGround(page)).toContain(THEMES.daylight.tokens.bg);
  expect(await mapGround(page)).toContain(THEMES.daylight.tokens.ground);
  expect(
    await page.evaluate(() =>
      document.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
    ),
  ).toBe(THEMES.daylight.tokens.bg);
});

test('switches the whole app at run time, with no reload and no layout shift', async ({ page }) => {
  await keep(page, 'daylight');
  await page.goto('/');
  await mapReady(page);
  await page.waitForTimeout(1500);
  const before = await page.evaluate(() => ({
    shifts: window.themeShifts ?? 0,
    navigations: performance.getEntriesByType('navigation').length,
    search: document.querySelector('.search')?.getBoundingClientRect().toJSON() as unknown,
  }));

  expect(await page.evaluate(() => window.snowlightTheme?.useTheme('aurora'))).toBe(true);
  await expect.poll(() => mapGround(page)).toContain(THEMES.aurora.tokens.ground);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
    rgb(THEMES.aurora.tokens.bg),
  );
  // The coasts in the theme's line color, a phone's a step clearer, as the page has it.
  const lines = await page.evaluate(
    (id) => ({
      map: window.snowlightMap?.getPaintProperty(id, 'line-color'),
      page: getComputedStyle(document.documentElement).getPropertyValue('--line-outline').trim(),
    }),
    BASEMAP_IDS.usOutline,
  );
  expect([THEMES.aurora.tokens.lineOutline, THEMES.aurora.tokens.lineOutlinePhone]).toContain(
    lines.page,
  );
  expect(lines.map).toBe(lines.page);

  // Back to Midnight: the page's own colors, and the map's.
  expect(await page.evaluate(() => window.snowlightTheme?.useTheme(null))).toBe(true);
  await expect.poll(() => mapGround(page)).toBe('"#000"');
  expect(await page.evaluate(() => document.documentElement.hasAttribute('data-theme'))).toBe(
    false,
  );

  await page.waitForTimeout(500);
  const after = await page.evaluate(() => ({
    shifts: window.themeShifts ?? 0,
    navigations: performance.getEntriesByType('navigation').length,
    search: document.querySelector('.search')?.getBoundingClientRect().toJSON() as unknown,
  }));
  expect(after.navigations).toBe(before.navigations);
  expect(after.shifts).toBe(before.shifts);
  expect(after.search).toEqual(before.search);
});

test('the map changes in the frame the page does, with no fade between the two', async ({
  page,
}) => {
  await keep(page, 'daylight');
  await page.goto('/');
  await mapReady(page);
  await page.waitForTimeout(1500);
  // Every frame the map draws from the change on: a pixel of its canvas, and the page's ground.
  const drawn = await page.evaluate(async () => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const canvas = map.getCanvas();
    const gl = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    if (gl === null) throw new Error('no WebGL');
    const pixel = (): number[] => {
      const out = new Uint8Array(4);
      gl.readPixels(4, gl.drawingBufferHeight - 4, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, out);
      return [...out.slice(0, 3)];
    };
    const frames: { pixel: number[]; ground: string }[] = [];
    const before = await new Promise<number[]>((resolve) => {
      map.once('render', () => {
        resolve(pixel());
      });
      map.triggerRepaint();
    });
    const onRender = (): void => {
      frames.push({ pixel: pixel(), ground: getComputedStyle(document.body).backgroundColor });
    };
    map.on('render', onRender);
    window.snowlightTheme?.useTheme('aurora');
    await new Promise((resolve) => setTimeout(resolve, 1200));
    map.triggerRepaint();
    await new Promise((resolve) => setTimeout(resolve, 300));
    map.off('render', onRender);
    return { before, frames };
  });
  const settled = drawn.frames.at(-1);
  if (settled === undefined) throw new Error('the map drew nothing after the change');
  const near = (a: number[], b: number[]): boolean =>
    a.every((channel, i) => Math.abs(channel - (b[i] ?? -1)) <= 2);
  // The theme changed the map's colors, and its first frame after is already its last.
  expect(near(drawn.before, settled.pixel)).toBe(false);
  expect(drawn.frames.filter((frame) => !near(frame.pixel, settled.pixel))).toEqual([]);
  expect(drawn.frames.filter((frame) => frame.ground !== rgb(THEMES.aurora.tokens.bg))).toEqual([]);
});

/** The frames recorded so far. */
async function frames(page: Page): Promise<{ theme: string | null; ground: string }[]> {
  return page.evaluate(() => window.themeFrames ?? []);
}

test('never puts on a theme waiting for approval, not for a single frame', async ({
  context,
  page,
}) => {
  await keep(page, 'snowball');
  const faces: string[] = [];
  page.on('request', (request) => {
    if (/fredoka|\.woff2/i.test(request.url()) && !/geist/i.test(request.url())) {
      faces.push(request.url());
    }
  });
  await page.goto('/');
  // The page is Midnight's own: index.html passes over the kept Snowball, and no engine loads.
  await page.waitForFunction(
    () => document.querySelector('svg.still') === null && window.snowlightMap?.isStyleLoaded(),
    null,
    { timeout: 60_000 },
  );
  const seen = await frames(page);
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.filter((frame) => frame.theme !== null)).toEqual([]);
  expect(seen.filter((frame) => frame.ground !== 'rgb(0, 0, 0)')).toEqual([]);
  // The id stays kept, for a build that carries it.
  expect(await page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY)).toBe(
    JSON.stringify({ id: 'snowball' }),
  );
  // The build carries none of it.
  expect(await page.content()).not.toMatch(/snowball|fredoka/i);

  // Another tab keeps it: the engine starts here to follow, and refuses it.
  const other = await context.newPage();
  await other.goto('/robots.txt');
  // Kept again there (a new value, so this tab hears it).
  await other.evaluate((key) => {
    localStorage.setItem(key, JSON.stringify({ id: 'snowball', from: 'another tab' }));
  }, THEME_STORAGE_KEY);
  await page.waitForFunction(() => window.snowlightTheme !== undefined, null, { timeout: 30_000 });
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('midnight');
  expect(await page.evaluate(() => document.documentElement.hasAttribute('data-theme'))).toBe(
    false,
  );
  expect(await page.evaluate(() => window.snowlightTheme?.useTheme('snowball'))).toBe(false);
  expect(await page.evaluate(() => window.snowlightTheme?.previewTheme('snowball'))).toBe(false);
  expect((await frames(page)).filter((frame) => frame.theme !== null)).toEqual([]);
  expect(faces).toEqual([]);
  expect(await page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY)).toBe(
    JSON.stringify({ id: 'snowball', from: 'another tab' }),
  );
});

test.describe('a tab of a build that does not carry the kept theme', () => {
  // Every page straight from the network, so the older build's page below is the one routed.
  test.use({ serviceWorkers: 'block' });

  /** Serves `page` this build's index.html without Daylight: an older build's, which lacks it. */
  async function olderBuild(page: Page): Promise<void> {
    await page.route(
      (url) => url.pathname === '/' || url.pathname === '/index.html',
      async (route) => {
        const response = await route.fetch();
        const html = (await response.text()).replace(
          /(<script type="application\/json" id="sl-themes">)([\s\S]*?)(<\/script>)/,
          (_all, open: string, json: string, close: string) => {
            const themes = JSON.parse(json) as Record<string, unknown>;
            if (themes.daylight === undefined) throw new Error('the page carries no Daylight');
            delete themes.daylight;
            return `${open}${JSON.stringify(themes)}${close}`;
          },
        );
        await route.fulfill({ response, body: html });
      },
    );
  }

  test('shows Midnight and leaves the theme kept for the tab that put it on', async ({
    context,
  }) => {
    // A newer build's tab, with Daylight on.
    const newer = await context.newPage();
    await keep(newer, 'daylight');
    await newer.goto('/');
    await mapReady(newer);
    const daylight = JSON.stringify({ id: 'daylight' });
    const stored = (tab: Page): Promise<string | null> =>
      tab.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY);

    // A tab of the older build opens with Daylight kept: Midnight from its first frame.
    const older = await context.newPage();
    await olderBuild(older);
    await record(older);
    await older.goto('/');
    await older.waitForFunction(() => window.snowlightMap?.isStyleLoaded() === true, null, {
      timeout: 60_000,
    });
    expect(await older.content()).not.toMatch(/"daylight"/);
    expect(await stored(older)).toBe(daylight);

    // The newer tab takes Daylight off and puts it on again: the older tab hears both, starts
    // its engine, and shows Midnight, writing nothing.
    expect(await newer.evaluate(() => window.snowlightTheme?.useTheme(null))).toBe(true);
    await older.waitForFunction(() => window.snowlightTheme !== undefined, null, {
      timeout: 30_000,
    });
    expect(await newer.evaluate(() => window.snowlightTheme?.useTheme('daylight'))).toBe(true);
    await older.waitForTimeout(2500);
    expect(await older.evaluate(() => window.snowlightTheme?.current)).toBe('midnight');
    expect(await stored(older)).toBe(daylight);
    expect(await newer.evaluate(() => window.snowlightTheme?.current)).toBe('daylight');
    expect(await newer.evaluate(() => document.documentElement.getAttribute('data-theme'))).toBe(
      'daylight',
    );
    expect(await mapGround(older)).toBe('"#000"');
    const seen = await frames(older);
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.filter((frame) => frame.theme !== null)).toEqual([]);
    expect(seen.filter((frame) => frame.ground !== 'rgb(0, 0, 0)')).toEqual([]);

    // Opened again on the older build, with Daylight kept: Midnight from the first frame, still kept.
    await older.reload();
    await older.waitForFunction(() => window.snowlightMap?.isStyleLoaded() === true, null, {
      timeout: 60_000,
    });
    await older.waitForTimeout(1500);
    const again = await frames(older);
    expect(again.length).toBeGreaterThan(0);
    expect(again.filter((frame) => frame.theme !== null)).toEqual([]);
    expect(again.filter((frame) => frame.ground !== 'rgb(0, 0, 0)')).toEqual([]);
    expect(await stored(older)).toBe(daylight);
    expect(await stored(newer)).toBe(daylight);
    expect(await newer.evaluate(() => window.snowlightTheme?.current)).toBe('daylight');
  });
});

test('shows only this build’s version of a kept theme, from the first frame', async ({ page }) => {
  // What an older build kept: its CSS, here with another ground. Only the id counts.
  await keep(page, 'daylight', {
    css: ':root{--bg:#ff00ff}body{background:#ff00ff}',
    color: '#f0f',
  });
  await page.goto('/');
  await mapReady(page);
  await page.waitForTimeout(1000);
  const seen = await frames(page);
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.filter((frame) => frame.ground !== rgb(THEMES.daylight.tokens.bg))).toEqual([]);
  expect(seen.filter((frame) => frame.theme !== 'daylight')).toEqual([]);
  // A kept theme loads with no layout shift.
  expect(await page.evaluate(() => window.themeShifts)).toBe(0);
});

test('the browser bar follows a change at run time', async ({ page }) => {
  await keep(page, 'ember');
  await page.goto('/');
  await mapReady(page);
  const barColor = (): Promise<string | null | undefined> =>
    page.evaluate(() =>
      document.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
    );
  expect(await barColor()).toBe(THEMES.ember.tokens.bg);
  await page.evaluate(() => window.snowlightTheme?.useTheme('daylight'));
  expect(await barColor()).toBe(THEMES.daylight.tokens.bg);
  await page.evaluate(() => window.snowlightTheme?.useTheme(null));
  expect(await barColor()).toBe('#000000');
});

test('every open tab follows a change made in one', async ({ context }) => {
  const first = await context.newPage();
  await first.goto('/');
  await first.waitForFunction(() => window.snowlightMap?.isStyleLoaded() === true, null, {
    timeout: 60_000,
  });
  const second = await context.newPage();
  await keep(second, 'daylight');
  await second.goto('/');
  await mapReady(second);
  expect(await second.evaluate(() => window.snowlightTheme?.useTheme('gold'))).toBe(true);
  // The first tab, in Midnight with no engine yet, starts it and follows.
  await expect
    .poll(() => first.evaluate(() => document.documentElement.getAttribute('data-theme')))
    .toBe('gold');
  await expect.poll(() => mapGround(first)).toContain(THEMES.gold.tokens.ground);
  await second.evaluate(() => window.snowlightTheme?.useTheme(null));
  await expect
    .poll(() => first.evaluate(() => document.documentElement.hasAttribute('data-theme')))
    .toBe(false);
});

test('a flat theme’s marks go under the national names, and the glow back over them', async ({
  page,
}) => {
  const order = (): Promise<{ glow: number; names: number[] }> =>
    page.evaluate(
      ([glow, city, state]) => {
        const layers = window.snowlightMap?.getLayersOrder() ?? [];
        // Every band of city names (style.ts cityNameLayerId), and the state names.
        const names = layers.flatMap((id, at) =>
          id === city || id.startsWith(`${city}-`) || id === state ? [at] : [],
        );
        return { glow: layers.indexOf(glow), names };
      },
      [BASEMAP_IDS.glow, BASEMAP_IDS.usCityLabel, BASEMAP_IDS.usStateLabel] as const,
    );
  await keep(page, 'daylight');
  await page.goto('/');
  await mapReady(page);
  await expect.poll(async () => (await order()).glow).toBeGreaterThan(-1);
  let now = await order();
  expect(now.names.length).toBeGreaterThan(1);
  for (const name of now.names) expect(now.glow).toBeLessThan(name);
  await page.evaluate(() => window.snowlightTheme?.useTheme('aurora'));
  now = await order();
  for (const name of now.names) expect(now.glow).toBeGreaterThan(name);
  await page.evaluate(() => window.snowlightTheme?.useTheme('daylight'));
  now = await order();
  for (const name of now.names) expect(now.glow).toBeLessThan(name);
});

/**
 * Whole-app themes in the built site (src/theme/engine.ts): a theme the
 * device keeps is on from the first paint, the page and the map change
 * together at run time with no reload and no layout shift, Snowball is
 * offered like every shop theme, with its style sheet and its face fetched
 * only where it goes on, and a theme still waiting for the owner's approval
 * (theme/unreleased.ts; none at present) is carried by no default build.
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
import { THEMES, THEME_IDS } from '../src/theme/themes';
import type { ThemeId } from '../src/theme/themes';
import { UNRELEASED_IDS } from '../src/theme/unreleased';

interface Engine {
  readonly current: ThemeId;
  /** Resolves true once the theme is on and kept (src/theme/engine.ts). */
  useTheme(id: ThemeId | null): Promise<boolean>;
  previewTheme(id: ThemeId): Promise<boolean>;
  endPreview(): void;
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

test('a default build carries no theme waiting for approval, and Snowball as a sheet of its own', () => {
  const files = readdirSync(DIST, { recursive: true, encoding: 'utf8' }).filter(
    (file) => !/\.(?:png|jpe?g|webp|avif|ico|woff2?|pmtiles|gz|br)$/i.test(file),
  );
  expect(files.length).toBeGreaterThan(10);
  const text = (file: string): string => {
    try {
      return readFileSync(path.join(DIST, file), 'utf8');
    } catch {
      // A directory.
      return '';
    }
  };
  // No waiting theme's name in any file, and no source map names their module (with none
  // waiting, a build with a stand-in listed is tested in src/theme/tests/build.test.ts).
  for (const id of UNRELEASED_IDS) {
    expect(files.filter((file) => text(file).includes(id))).toEqual([]);
  }
  expect(
    files.filter(
      (file) =>
        file.endsWith('.map') &&
        (JSON.parse(text(file)) as { sources: string[] }).sources.some((source) =>
          source.endsWith('theme/unreleased.ts'),
        ),
    ),
  ).toEqual([]);
  // No script the page runs carries Snowball's palette (nor any theme's): the page carries its
  // CSS, the engine the ids alone, and only a shop's script, outside what the worker precaches,
  // the palettes.
  const palette = [THEMES.snowball.tokens.surface1, THEMES.snowball.tokens.border1];
  expect(
    files.filter(
      (file) =>
        file.endsWith('.js') &&
        !file.startsWith('assets/themes/') &&
        palette.some((color) => text(file).includes(color)),
    ),
  ).toEqual([]);
  // Snowball's rules are in its own sheet alone, which the service worker does not precache, nor
  // its face: a device that never puts it on downloads neither.
  const rules = files.filter(
    (file) => !file.endsWith('.map') && text(file).includes("[data-theme='snowball']"),
  );
  expect(rules).toEqual([expect.stringMatching(/^assets\/themes\/snowball-[\w-]+\.css$/)]);
  expect(text('sw.js')).not.toMatch(/themes\/snowball|fredoka/i);
  const page = text('index.html');
  expect(page).not.toMatch(/@font-face[^}]*Fredoka/);
  const carried = /<script type="application\/json" id="sl-themes">([\s\S]*?)<\/script>/.exec(
    page,
  )?.[1];
  expect(Object.keys(JSON.parse(carried ?? '{}') as object)).toEqual(
    THEME_IDS.filter((id) => id !== 'midnight'),
  );
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
    void window.snowlightTheme?.useTheme('aurora');
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

/** Every request for Snowball's own files: its style sheet and its face. */
function snowballFiles(page: Page): string[] {
  const asked: string[] = [];
  page.on('request', (request) => {
    if (/themes\/snowball|fredoka/i.test(request.url())) asked.push(request.url());
  });
  return asked;
}

test('a device on another theme fetches nothing of Snowball', async ({ page }) => {
  const asked = snowballFiles(page);
  await record(page);
  await page.goto('/');
  await page.waitForFunction(() => window.snowlightMap?.isStyleLoaded() === true, null, {
    timeout: 60_000,
  });
  await page.waitForTimeout(1500);
  expect(asked).toEqual([]);
  // Nor a device on Aurora, whose engine runs.
  await page.evaluate((key) => {
    localStorage.setItem(key, JSON.stringify({ id: 'aurora' }));
  }, THEME_STORAGE_KEY);
  await page.reload();
  await mapReady(page);
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('aurora');
  expect(asked).toEqual([]);
});

test('tries Snowball, puts it on and keeps it across a reload, its face fetched only then', async ({
  page,
}) => {
  // Aurora kept once, before the first load only: the reload below opens with what the page kept.
  await page.addInitScript((key) => {
    if (sessionStorage.getItem('kept once') !== null) return;
    sessionStorage.setItem('kept once', 'yes');
    localStorage.setItem(key, JSON.stringify({ id: 'aurora' }));
  }, THEME_STORAGE_KEY);
  await record(page);
  const asked = snowballFiles(page);
  await page.goto('/');
  await mapReady(page);
  await page.waitForTimeout(1000);
  expect(asked).toEqual([]);

  // Tried: the whole page and the map in Snowball, in its own face, and nothing kept.
  expect(await page.evaluate(() => window.snowlightTheme?.previewTheme('snowball'))).toBe(true);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
    .toBe('snowball');
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
    rgb(THEMES.snowball.tokens.bg),
  );
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toMatch(
    /^"?Fredoka Variable"?,/,
  );
  expect(await page.evaluate(() => document.fonts.check("16px 'Fredoka Variable'"))).toBe(true);
  await expect.poll(() => mapGround(page)).toContain(THEMES.snowball.tokens.ground);
  expect(asked.some((url) => /\/assets\/themes\/snowball-[\w-]+\.css$/.test(url))).toBe(true);
  expect(asked.some((url) => url.includes('fredoka-latin-wght'))).toBe(true);
  // It went on in one change: no frame of Snowball's attribute on another ground.
  expect(
    (await frames(page)).filter(
      (frame) => frame.theme === 'snowball' && frame.ground !== rgb(THEMES.snowball.tokens.bg),
    ),
  ).toEqual([]);
  expect(await page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY)).toBe(
    JSON.stringify({ id: 'aurora' }),
  );
  await page.evaluate(() => {
    window.snowlightTheme?.endPreview();
  });
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('aurora');

  // Put on and kept.
  expect(await page.evaluate(() => window.snowlightTheme?.useTheme('snowball'))).toBe(true);
  await expect.poll(() => page.evaluate(() => window.snowlightTheme?.current)).toBe('snowball');
  expect(await page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY)).toBe(
    JSON.stringify({ id: 'snowball' }),
  );

  // Opened again: Snowball from the first frame, page and map, with no layout shift.
  await page.reload();
  await mapReady(page);
  await page.waitForTimeout(1000);
  const seen = await frames(page);
  expect(seen.length).toBeGreaterThan(0);
  expect(seen.filter((frame) => frame.theme !== 'snowball')).toEqual([]);
  expect(seen.filter((frame) => frame.ground !== rgb(THEMES.snowball.tokens.bg))).toEqual([]);
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('snowball');
  await expect.poll(() => mapGround(page)).toContain(THEMES.snowball.tokens.ground);
  expect(
    await page.evaluate(() =>
      document.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
    ),
  ).toBe(THEMES.snowball.tokens.bg);
  expect(await page.evaluate(() => window.themeShifts)).toBe(0);
});

test('a kept Snowball whose sheet cannot load shows Midnight, bar and all, until it loads', async ({
  page,
}) => {
  await keep(page, 'snowball');
  let refuse = true;
  let refused = 0;
  await page.route(/\/assets\/themes\/snowball-[\w-]+\.css$/, async (route) => {
    if (!refuse) {
      await route.continue();
      return;
    }
    refused += 1;
    await route.abort();
  });
  const bar = (): Promise<string | null | undefined> =>
    page.evaluate(() =>
      document.querySelector('meta[name="theme-color"]')?.getAttribute('content'),
    );
  await page.goto('/');
  await mapReady(page);
  // The first script's sheet, then the engine's try again: both refused.
  await expect.poll(() => refused).toBe(2);
  await page.waitForTimeout(1000);
  const seen = await frames(page);
  expect(seen.length).toBeGreaterThan(0);
  // Midnight from the first frame, never Snowball's mark on it, and the bar Midnight's.
  expect(seen.filter((frame) => frame.theme !== null)).toEqual([]);
  expect(seen.filter((frame) => frame.ground !== rgb(THEMES.midnight.tokens.bg))).toEqual([]);
  expect(await bar()).toBe(THEMES.midnight.tokens.bg);
  expect(await page.evaluate(() => window.snowlightTheme?.current)).toBe('midnight');
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).not.toMatch(
    /Fredoka/,
  );
  // Kept still, for the next visit, and nothing moved.
  expect(await page.evaluate((key) => localStorage.getItem(key), THEME_STORAGE_KEY)).toBe(
    JSON.stringify({ id: 'snowball' }),
  );
  expect(await page.evaluate(() => window.themeShifts)).toBe(0);
  // Put on again once the sheet can load: Snowball, in one change.
  refuse = false;
  expect(await page.evaluate(() => window.snowlightTheme?.useTheme('snowball'))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('snowball');
  expect(await bar()).toBe(THEMES.snowball.tokens.bg);
  expect(
    (await frames(page)).filter(
      (frame) => frame.theme === 'snowball' && frame.ground !== rgb(THEMES.snowball.tokens.bg),
    ),
  ).toEqual([]);
  expect(await page.evaluate(() => window.themeShifts)).toBe(0);
});

test('every open tab follows Snowball put on in one', async ({ context }) => {
  const first = await context.newPage();
  await record(first);
  await first.goto('/');
  await first.waitForFunction(() => window.snowlightMap?.isStyleLoaded() === true, null, {
    timeout: 60_000,
  });
  const second = await context.newPage();
  await keep(second, 'daylight');
  await second.goto('/');
  await mapReady(second);
  expect(await second.evaluate(() => window.snowlightTheme?.useTheme('snowball'))).toBe(true);
  // The first tab, in Midnight with no engine yet, starts it and follows, page and map.
  await expect
    .poll(() => first.evaluate(() => document.documentElement.getAttribute('data-theme')), {
      timeout: 30_000,
    })
    .toBe('snowball');
  expect(await first.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
    rgb(THEMES.snowball.tokens.bg),
  );
  await expect.poll(() => mapGround(first)).toContain(THEMES.snowball.tokens.ground);
  expect(
    (await frames(first)).filter(
      (frame) => frame.theme === 'snowball' && frame.ground !== rgb(THEMES.snowball.tokens.bg),
    ),
  ).toEqual([]);
  await second.evaluate(() => window.snowlightTheme?.useTheme(null));
  await expect
    .poll(() => first.evaluate(() => document.documentElement.hasAttribute('data-theme')))
    .toBe(false);
  expect(await first.evaluate(() => getComputedStyle(document.body).fontFamily)).not.toMatch(
    /Fredoka/,
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

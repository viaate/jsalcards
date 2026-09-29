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
 *   pipeline wrote them, and three more near Kansas City for the chance
 *   section (Shawnee Mission East and a school in each district next door).
 *   Its closings and predictions files are SYNTHETIC: no real closings or
 *   forecasts exist in September, so the statuses, the storm and its chances
 *   are made up for this test and live only in the temporary folder while it
 *   runs. So are its season stats and track record, for the menu: the
 *   pipeline publishes neither yet.
 *
 * Runs once, under the desktop project; tests set their own viewports.
 * WebGL here is SwiftShader, whose frames are slow, and a page's first flight
 * into streets holds the page for seconds (FIRST_FLIGHT_MS). A test that
 * waits on the map or on a timer waits in real time, with the date fixed
 * alone (fixDate): a faked clock would stretch each by the frames it draws.
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
import type { Locator, Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

import { STATUS_KEYS, copy } from '../src/copy';
import { chanceCopy, chanceFormat } from '../src/copy-chance';
import { format } from '../src/copy-format';
import { COPIED_MS } from '../src/ui/share';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GLOW_LAYER = 'snowlight-glow';
const FIRST_LABEL_LAYER = 'ofm-label-neighbourhood';
const PEMBROKE_HILL = 'A1902690';
const BORDER_STAR = { lon: -94.592692, lat: 39.013304 };
/**
 * Where the school panel beside the map ends on a 1440 px screen: its gap from the screen's
 * edge and its width there (app/frame.ts PANEL_WIDTHS).
 */
const PANEL_RIGHT = 20 + 460;
/** Where Pembroke Hill is, as the directory has it. */
const PEMBROKE_HILL_PLACE = { lon: -94.593001, lat: 39.03606 };
const SHAWNEE_MISSION_EAST = '201164001574';
const PIN_KEY = 'snowlight:pin';
/** Chrome's own lines about SwiftShader, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;
/** Playwright's own line when a test blocks the service worker, not the page's. */
const BLOCKED_WORKER = 'Service Worker registration blocked by Playwright';

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
    const text = message.text();
    if (
      (type === 'error' || type === 'warning') &&
      !GPU_DRIVER_NOISE.test(text) &&
      text !== BLOCKED_WORKER
    ) {
      problems.push(`console.${type}: ${text}`);
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

/**
 * Stops the page's calendar at `now`, and nothing else: `new Date()` and `Date.now()` give `now`,
 * while timers, animation frames and performance.now run as they do. page.clock fakes those too,
 * and its time then moves on 16 ms for each frame the page draws: where a frame takes longer, as
 * the map's do in software, a flight or a timer takes that many times as long in real time.
 */
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

/** Every layout shift the page has had, by the text of what moved: none is ever expected. */
async function layoutShifts(page: Page): Promise<string[]> {
  return page.evaluate(
    () =>
      new Promise<string[]>((resolve) => {
        const done = (shifts: string[]): void => {
          observer.disconnect();
          resolve(shifts);
        };
        const observer = new PerformanceObserver((list) => {
          done(
            list.getEntries().map((entry) => {
              const { value, sources } = entry as unknown as {
                value: number;
                sources: { node?: Node | null }[];
              };
              const moved = sources.map((source) => source.node?.textContent?.trim() ?? '?');
              return `${String(value)} ${moved.join(' | ')}`;
            }),
          );
        });
        // Buffered: the shifts so far come at once, and with none nothing comes.
        observer.observe({ type: 'layout-shift', buffered: true });
        setTimeout(() => {
          done([]);
        }, 500);
      }),
  );
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

/** Resolves once the map is at rest with every tile in. */
async function settleMap(page: Page): Promise<void> {
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout: 30_000, polling: 100 },
  );
}

/** Where a place is on the screen, in CSS pixels. */
async function onScreen(
  page: Page,
  place: { readonly lon: number; readonly lat: number },
): Promise<{ x: number; y: number }> {
  return page.evaluate(({ lon, lat }) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const point = map.project([lon, lat]);
    const box = map.getContainer().getBoundingClientRect();
    return { x: box.left + point.x, y: box.top + point.y };
  }, place);
}

async function mapView(page: Page): Promise<{ lat: number; lon: number; zoom: number }> {
  return page.evaluate(() => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const center = map.getCenter();
    return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
  });
}

/**
 * How long a page's first flight into streets may take here. The first frames that draw the
 * street layers hold the page while the software renderer builds what it draws them with: 10 to
 * 20 s on a busy machine (Chrome's trace: the frame's commit waits in ReadPixels on
 * ContextVk::finishImpl), on top of the flight's own seconds. Later flights take seconds.
 */
const FIRST_FLIGHT_MS = 90_000;

/**
 * Resolves once the map has come to rest near a place. The map is waited for first: a linked
 * school's panel can show before MapLibre has loaded, and a poll that throws is not polled again.
 */
async function expectMapNear(
  page: Page,
  lat: number,
  lon: number,
  zoom: number,
  timeout = 30_000,
): Promise<void> {
  await page.waitForFunction(() => window.snowlightMap !== undefined, null, { timeout });
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
      { timeout },
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

  test('the menu opens from its button beside the field: what the map shows and About, asking nothing of data/', async ({
    browser,
  }) => {
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
    ]) {
      const where = `${String(viewport.width)}x${String(viewport.height)}`;
      const context = await browser.newContext({ viewport });
      const page = await context.newPage();
      const { problems, requests } = watch(page);
      await page.goto('/');
      await waitForMap(page);
      const button = page.getByRole('button', { name: copy.menu.label, exact: true });
      await expect(button).toHaveAttribute('aria-expanded', 'false');

      await button.click();
      const menu = page.locator('aside.menu');
      await expect(menu).toBeVisible();
      await arrived(menu);
      await expect(button).toHaveAttribute('aria-expanded', 'true');
      await expect(button).toHaveAttribute('aria-controls', (await menu.getAttribute('id')) ?? '');
      await expect(menu).toBeFocused();
      await expect(menu).toHaveAttribute('aria-label', copy.menu.label);
      // Today's statuses and the kinds of school, then About: all four statuses in use on the
      // pill, nothing counted, and nothing says there is nothing.
      await expect(menu.locator('h2')).toHaveText([copy.menu.today, copy.menu.kinds]);
      await expect(menu.locator('.item .name')).toHaveText([
        copy.menu.all,
        ...STATUS_KEYS.map((key) => copy.status[key]),
        copy.menu.public,
        copy.menu.private,
        copy.nav.about,
      ]);
      await expect(menu.locator('.item.is-on .name')).toHaveText([copy.menu.all]);
      await expect(menu.getByRole('radio', { name: copy.menu.all })).toBeChecked();
      await expect(menu.getByRole('checkbox', { name: copy.menu.public })).toBeChecked();
      await expect(menu.getByRole('checkbox', { name: copy.menu.private })).toBeChecked();
      await expect(menu.locator('.value:not(:empty)')).toHaveCount(0);
      expect(await menu.textContent()).not.toMatch(/not enough|no data/iu);
      await expectMenuGrid(menu, viewport.width >= 720 ? 40 : 44, where);

      // Under the field and lined up with it (at a desktop's size its left edge on the field's),
      // clear of the key at the foot of the screen, and nothing on it moved.
      const field = await page.locator('.search').boundingBox();
      const panel = await menu.boundingBox();
      const legend = await page.locator('ul.legend').boundingBox();
      if (field === null || panel === null || legend === null) throw new Error('no box');
      expect(panel.y, where).toBe(field.y + field.height + 8);
      if (viewport.width >= 720) {
        expect(panel.x, where).toBe(field.x);
        expect(panel.x, where).toBe(124);
        expect(panel.width, where).toBeLessThan(field.width);
        expect(panel.y + panel.height, where).toBeLessThan(legend.y);
      } else {
        expect(panel.x, where).toBe(field.x);
        expect(panel.width, where).toBe(field.width);
      }
      expect(await layoutShifts(page), where).toEqual([]);

      // About opens its page: what the site is and how to read its lights, nothing counted, and
      // the way back, which goes back to the list and to About's row.
      await menu.getByRole('button', { name: copy.nav.about }).click();
      const back = menu.getByRole('button', { name: copy.detail.back, exact: true });
      await expect(back).toBeFocused();
      await expect(menu.locator('.lead')).toHaveText(copy.about.what);
      await expect(menu.locator('.text')).toHaveText([copy.about.glow]);
      await expect(menu.locator('dl, table')).toHaveCount(0);
      await back.click();
      await expect(menu.getByRole('button', { name: copy.nav.about })).toBeFocused();

      // One status chosen: its row takes the pill, the key steps back from the others, and the
      // button says the map shows less than everything; all four again, and it is as it was.
      await menu.locator('label.item', { hasText: copy.status.closed }).click();
      await expect(menu.locator('.item.is-on .name')).toHaveText([copy.status.closed]);
      await expect.poll(() => keyMarks(page)).toEqual([1, 0.4, 0.4, 0.4]);
      await expect.poll(() => filteredDot(page)).toBe(true);
      await menu.locator('label.item', { hasText: copy.menu.all }).click();
      await expect.poll(() => keyMarks(page)).toEqual([1, 1, 1, 1]);
      await expect.poll(() => filteredDot(page)).toBe(false);

      // Escape closes it and gives the keyboard back to the button.
      await page.keyboard.press('Escape');
      await expect(menu).toHaveCount(0);
      await expect(button).toHaveAttribute('aria-expanded', 'false');
      await expect(button).toBeFocused();

      // A press on the map closes it too, and it opens again on its list.
      await button.click();
      await expect(menu).toBeVisible();
      await expect(menu.locator('h2')).toHaveText([copy.menu.today, copy.menu.kinds]);
      await page.mouse.click(viewport.width - 60, viewport.height - 150);
      await expect(menu).toHaveCount(0);

      await page.waitForTimeout(500);
      expect(requests.filter((url) => new URL(url).pathname.includes('/data/'))).toEqual([]);
      expect(problems).toEqual([]);
      await context.close();
    }
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

/**
 * Those two schools as the pipeline's directory has them (schools/meta.json, points.bin),
 * and three near Kansas City for the chance section, in the directory's order (by id).
 */
const DIRECTORY_SCHOOLS = [
  {
    id: '201014000137',
    name: 'Olathe North Sr High',
    lon: -94.8093,
    lat: 38.888,
    district: 0,
    kind: 0,
  },
  {
    id: SHAWNEE_MISSION_EAST,
    name: 'Shawnee Mission East High',
    lon: -94.631999,
    lat: 38.991687,
    district: 1,
    kind: 0,
  },
  {
    id: '201200000112',
    name: 'Blue Valley High',
    lon: -94.656,
    lat: 38.839,
    district: 2,
    kind: 0,
  },
  {
    id: '291640000557',
    name: 'BORDER STAR MONTESSORI',
    lon: -94.592692,
    lat: 39.013304,
    district: 3,
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
/** The directory's districts, in its order (by id). */
const DISTRICTS = [
  ['2010140', 'Olathe'],
  ['2011640', 'Shawnee Mission Pub Sch'],
  ['2012000', 'Blue Valley'],
  ['2916400', 'KANSAS CITY 33'],
] as const;
const STAMP = {
  generated_on: DIRECTORY_ON,
  schools: DIRECTORY_SCHOOLS.length,
  districts: DISTRICTS.length,
};

function directoryMeta(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: DIRECTORY_ON,
    count: DIRECTORY_SCHOOLS.length,
    ids: DIRECTORY_SCHOOLS.map((school) => school.id),
    names: DIRECTORY_SCHOOLS.map((school) => school.name),
    districts: {
      ids: DISTRICTS.map(([id]) => id),
      names: DISTRICTS.map(([, name]) => name),
    },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

function directoryPoints(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * DIRECTORY_SCHOOLS.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(DIRECTORY_SCHOOLS.length, 8);
  bytes.writeUInt32LE(DISTRICTS.length, 12);
  DIRECTORY_SCHOOLS.forEach((school, i) => {
    const at = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), at);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), at + 4);
    bytes.writeUInt32LE(school.district, at + 8);
    bytes.writeUInt8(school.kind, at + 12);
  });
  return bytes;
}

/**
 * Those schools as the directory's own tables list them (the detail files
 * scripts/stage-data.mjs writes, src/data/details-format.ts), one shard and its index.
 */
function directoryDetails(): { index: string; shard: string } {
  const directory = STAMP;
  const kansas = (
    id: string,
    name: string,
    district: number,
    street: string,
    city: string,
    zip: string,
    enrollment: number,
    phone: string,
  ): unknown[] => {
    const [districtId, districtName] = DISTRICTS[district] ?? ['', ''];
    return [
      id,
      name,
      0,
      district,
      districtId,
      districtName,
      street,
      city,
      'KS',
      zip,
      'Johnson County',
      '09',
      '12',
      enrollment,
      phone,
      [],
    ];
  };
  const rows = [
    kansas(
      '201014000137',
      'Olathe North Sr High',
      0,
      '600 E Prairie St',
      'Olathe',
      '66061',
      2011,
      '9137807140',
    ),
    kansas(
      SHAWNEE_MISSION_EAST,
      'Shawnee Mission East High',
      1,
      '7500 Mission Rd',
      'Prairie Village',
      '66208',
      1737,
      '9139936600',
    ),
    kansas(
      '201200000112',
      'Blue Valley High',
      2,
      '6001 W. 159th St.',
      'Stilwell',
      '66085',
      1396,
      '9132394800',
    ),
    [
      '291640000557',
      'BORDER STAR MONTESSORI',
      0,
      3,
      '2916400',
      'KANSAS CITY 33',
      '6321 WORNALL RD',
      'KANSAS CITY',
      'MO',
      '64113',
      'Jackson County',
      'PK',
      '06',
      251,
      '8164185150',
      [[4, PEMBROKE_HILL, 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS', 2530, -94.593001, 39.03606]],
    ],
    [
      PEMBROKE_HILL,
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      1,
      null,
      null,
      null,
      '400 W 51ST ST',
      'KANSAS CITY',
      'MO',
      '64112',
      'Jackson County',
      'PK',
      '12',
      1174,
      '8169361230',
      [[3, '291640000557', 'BORDER STAR MONTESSORI', 2530, -94.592692, 39.013304]],
    ],
  ];
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory,
      shards: 1,
      first_ids: [DIRECTORY_SCHOOLS[0].id],
      files: ['0.json'],
    }),
    shard: JSON.stringify({ schema_version: 1, directory, first: 0, rows }),
  };
}

/** SYNTHETIC: made-up statuses for Border Star and Pembroke Hill, for this test only. */
const SYNTHETIC_DAY = '2026-01-12';
const SYNTHETIC_NOW = new Date('2026-01-12T18:00:00Z');
function syntheticClosings(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:42:00Z',
    directory: STAMP,
    days: [
      {
        day: SYNTHETIC_DAY,
        gaps: [3, 0],
        statuses: [0, 1],
        announced: [98, 40],
        reasons: [0, 1],
        shifts: [120],
        clocks: [null],
      },
    ],
  });
}

/** SYNTHETIC: a made-up season for the menu, for this test only, adding up as the pipeline's must. */
function syntheticSeason(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:42:00Z',
    season: '2025-2026',
    through: '2026-01-12',
    days: [
      ['2026-01-05', 1, 0, 0, 0],
      ['2026-01-12', 1, 1, 0, 0],
    ],
    states: [['MO', 2, 1, 0, 0]],
    schools: 2,
    districts: 1,
  });
}

/** SYNTHETIC: a made-up track record for the menu, for this test only. */
function syntheticTrackRecord(): string {
  const calibration = (given: number, happened: number) => ({
    forecasts: given,
    outcomes: happened,
    bins: Array.from({ length: 10 }, (_, n) => [
      n * 10,
      n * 10 + 10,
      n === 8 ? given : 0,
      n === 8 ? happened : 0,
    ]),
  });
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:42:00Z',
    first_day: '2026-01-05',
    last_day: '2026-01-12',
    leads: [{ lead_days: 1, no_school: calibration(4, 3), delay: calibration(0, 0) }],
  });
}

/** SYNTHETIC: that Monday at 9:05 PM in Kansas City, the evening before the made-up storm. */
const EVENING = new Date('2026-01-13T03:05:00Z');
const ZONE = 'America/Chicago';

/**
 * SYNTHETIC: the live file that evening at 9:00 PM. Monday's two statuses as before, and for
 * Tuesday, Blue Valley (8:41 PM) and Olathe (8:52 PM), next door to Shawnee Mission, canceled.
 */
function syntheticEveningClosings(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-13T03:00:00Z',
    directory: STAMP,
    days: [
      {
        day: SYNTHETIC_DAY,
        gaps: [3, 0],
        statuses: [0, 1],
        announced: [956, 898],
        reasons: [0, 1],
        shifts: [120],
        clocks: [null],
      },
      {
        day: '2026-01-13',
        gaps: [0, 1],
        statuses: [0, 0],
        announced: [8, 19],
        reasons: [0, 0],
        shifts: [],
        clocks: [],
      },
    ],
  });
}

/**
 * SYNTHETIC: the chances made that evening, in the shape the prediction engine is to write
 * (pipeline/snowlight/schemas/predictions.py). Shawnee Mission (district 1): 64% for Tuesday,
 * the snow on the ground hour by hour and how that adds up. Kansas City 33 (district 3), closed
 * Monday: 22% for Tuesday, with how cold it will feel. Olathe and Blue Valley: no forecast.
 */
function syntheticPredictions(): string {
  const nothing = { state: 'no_threat' };
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-13T03:00:00Z',
    directory: STAMP,
    days: ['2026-01-12', '2026-01-13'],
    districts: [
      {
        district: 1,
        time_zone: ZONE,
        neighbors: [2, 0],
        days: [
          nothing,
          {
            state: 'forecast',
            p_no_school: 0.64,
            p_delay: 0.18,
            reasons: [0, 2],
            previous: { p_no_school: 0.41, at: '2026-01-12T23:00:00Z' },
            announces_at: '2026-01-13T11:30:00Z',
            buses_at: '2026-01-13T13:00:00Z',
            hours: {
              kind: 'snow_total',
              start: '2026-01-13T03:00:00Z',
              values: [0.0, 0.0, 0.2, 0.6, 1.1, 1.8, 3.3, 4.8, 6.3, 7.1, 7.5],
              low: 6.0,
              high: 9.0,
              heavy: { first: 6, last: 8 },
            },
            why: {
              base: { kind: 'alert', points: 30, alert: 'winter_storm_warning' },
              reasons: [
                { kind: 'snow_total', points: 16, low: 6.0, high: 9.0, overnight: true },
                { kind: 'neighbors', points: 9, districts: [2, 0], status: 0 },
                {
                  kind: 'timing',
                  points: 7,
                  start: '2026-01-13T08:00:00Z',
                  end: '2026-01-13T11:00:00Z',
                },
                { kind: 'wind_chill', points: 5, feels_like: -4 },
                { kind: 'snow_stops', points: -3, at: '2026-01-13T13:00:00Z' },
              ],
            },
            record: {
              proves: 'snow_total',
              inches: 6.0,
              days: [
                { day: '2024-01-09', inches: 8.0, status: 0 },
                { day: '2025-01-06', inches: 10.0, status: 0 },
                { day: '2025-01-10', inches: 6.0, status: 0 },
                { day: '2025-02-05', inches: 6.0, status: 1 },
                { day: '2025-02-18', inches: 7.0, status: 0 },
              ],
            },
            events: [],
          },
        ],
      },
      {
        district: 3,
        time_zone: ZONE,
        neighbors: [],
        days: [
          nothing,
          {
            state: 'forecast',
            p_no_school: 0.22,
            p_delay: 0.31,
            reasons: [2, 0],
            previous: { p_no_school: 0.3, at: '2026-01-12T15:00:00Z' },
            announces_at: '2026-01-13T11:30:00Z',
            buses_at: '2026-01-13T13:00:00Z',
            hours: {
              kind: 'wind_chill',
              start: '2026-01-13T03:00:00Z',
              values: [-1.0, -2.0, -3.0, -3.0, -4.0, -5.0, -6.0, -6.0, -7.0, -8.0, -8.0],
              low: null,
              high: null,
              heavy: null,
            },
            why: {
              base: { kind: 'day_after', points: 25 },
              reasons: [
                { kind: 'snow_stops', points: -8, at: '2026-01-12T12:00:00Z' },
                { kind: 'cold', points: 6, feels_like: -8 },
                { kind: 'sun', points: -5 },
                { kind: 'icy_roads', points: 4, inches: 8.0 },
              ],
            },
            record: {
              proves: 'base',
              inches: null,
              days: [
                { day: '2024-01-10', inches: null, status: null },
                { day: '2025-01-07', inches: null, status: 0 },
                { day: '2025-01-13', inches: null, status: null },
                { day: '2025-02-19', inches: null, status: null },
              ],
            },
            events: [{ kind: 'snow_stopped', at: '2026-01-12T12:00:00Z', inches: 8.0 }],
          },
        ],
      },
    ],
  });
}

/** SYNTHETIC: that Monday at 1:05 AM in Kansas City, a day and a half before Tuesday's buses. */
const SHAPE_NOW = new Date('2026-01-12T07:05:00Z');
const SHAPE_BUSES = '2026-01-13T13:00:00Z';

/** SYNTHETIC: a night for the chart to draw, and how many bars it takes. */
interface NightShape {
  readonly name: string;
  readonly kind: 'snow_total' | 'wind_chill';
  readonly start: string;
  readonly values: readonly number[];
  readonly range: readonly [number, number] | null;
  readonly heavy: { readonly first: number; readonly last: number } | null;
  readonly announces: string;
  readonly bars: number;
}

/**
 * Snow on the ground since the storm began, hour by hour, in tenths, up to `total`: three times
 * as fast in the heaviest hours (value i is the snow at the end of the hour before it).
 */
function snowNight(
  length: number,
  heavy: { first: number; last: number } | null,
  total: number,
): number[] {
  const weights = Array.from({ length }, (_, i): number =>
    i === 0 ? 0 : heavy !== null && i >= heavy.first && i <= heavy.last ? 3 : 1,
  );
  const sum = weights.reduce((a, b) => a + b, 0);
  let running = 0;
  return weights.map((weight) => {
    running += weight;
    return Math.round((running / sum) * total * 10) / 10;
  });
}

/** The nights the chart's words must fit around: long and short, the heaviest early, late and at the end. */
const NIGHT_SHAPES: readonly NightShape[] = [
  {
    name: 'thirty hours, two to a bar, the heaviest early, the announcement after it',
    kind: 'snow_total',
    start: '2026-01-12T07:00:00Z',
    values: snowNight(31, { first: 3, last: 8 }, 12.3),
    range: [10.5, 14.5],
    heavy: { first: 3, last: 8 },
    announces: '2026-01-13T11:30:00Z',
    bars: 16,
  },
  {
    name: 'the heaviest at the bus hour, the announcement inside it',
    kind: 'snow_total',
    start: '2026-01-13T01:00:00Z',
    values: snowNight(13, { first: 10, last: 12 }, 12.3),
    range: [10.5, 14.5],
    heavy: { first: 10, last: 12 },
    announces: '2026-01-13T11:30:00Z',
    bars: 13,
  },
  {
    name: 'eighteen bars, the announcement the evening before, ahead of the heaviest',
    kind: 'snow_total',
    start: '2026-01-12T20:00:00Z',
    values: snowNight(18, { first: 12, last: 15 }, 8.8),
    range: [7.5, 10.5],
    heavy: { first: 12, last: 15 },
    announces: '2026-01-13T02:00:00Z',
    bars: 18,
  },
  {
    name: 'twenty hours, two to a bar, the heaviest at the start, no range',
    kind: 'snow_total',
    start: '2026-01-12T18:00:00Z',
    values: snowNight(20, { first: 1, last: 4 }, 0.8),
    range: null,
    heavy: { first: 1, last: 4 },
    announces: '2026-01-13T11:30:00Z',
    bars: 10,
  },
  {
    name: 'thirty hours of cold',
    kind: 'wind_chill',
    start: '2026-01-12T07:00:00Z',
    values: Array.from({ length: 31 }, (_, i) => -2 - Math.round(i * 0.8)),
    range: null,
    heavy: null,
    announces: '2026-01-13T11:30:00Z',
    bars: 16,
  },
];

/**
 * SYNTHETIC: Shawnee Mission's (district 1) chance for Tuesday, 64%, with the night `shape`
 * draws; Monday has no threat.
 */
function shapedPredictions(shape: NightShape): string {
  const snow = shape.kind === 'snow_total';
  const last = shape.values.at(-1) ?? 0;
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T07:00:00Z',
    directory: STAMP,
    days: ['2026-01-12', '2026-01-13'],
    districts: [
      {
        district: 1,
        time_zone: ZONE,
        neighbors: [2, 0],
        days: [
          { state: 'no_threat' },
          {
            state: 'forecast',
            p_no_school: 0.64,
            p_delay: 0.18,
            reasons: [0],
            previous: null,
            announces_at: shape.announces,
            buses_at: SHAPE_BUSES,
            hours: {
              kind: shape.kind,
              start: shape.start,
              values: shape.values,
              low: shape.range?.[0] ?? null,
              high: shape.range?.[1] ?? null,
              heavy: shape.heavy,
            },
            why: {
              base: { kind: 'alert', points: 50, alert: 'winter_storm_warning' },
              reasons: [
                snow
                  ? {
                      kind: 'snow_total',
                      points: 14,
                      low: shape.range?.[0] ?? last,
                      high: shape.range?.[1] ?? last,
                      overnight: true,
                    }
                  : { kind: 'wind_chill', points: 14, feels_like: last },
              ],
            },
            record: null,
            events: [],
          },
        ],
      },
    ],
  });
}

/** Opens a school, or closes it, as the back button would: the address, then popstate. */
async function showSchool(page: Page, id: string | null): Promise<void> {
  await page.evaluate((school) => {
    const url = new URL(location.href);
    if (school === null) url.searchParams.delete('school');
    else url.searchParams.set('school', school);
    history.pushState(null, '', url);
    dispatchEvent(new PopStateEvent('popstate'));
  }, id);
}

/**
 * The chance chart as laid out: every bar 3 px wide or more; the times at its foot inside the
 * plot, none meeting another; the dashed lines' words over the plot inside it, none meeting
 * another, a bar, the range or a time; the key's rows inside the panel, none cut off, none
 * meeting another or a time; and nothing in the panel scrolling sideways.
 */
async function expectChartFits(page: Page, label: string): Promise<void> {
  const layout = await page.locator('aside.detail').evaluate((panel) => {
    const box = (node: Element) => {
      const { x, y, width, height } = node.getBoundingClientRect();
      return { x, y, width, height };
    };
    const chart = panel.querySelector('.chance .chart');
    const plot = chart?.querySelector('.plot') ?? null;
    const body = panel.querySelector('.body') ?? panel;
    return {
      panel: box(panel),
      plot: plot === null ? null : box(plot),
      bars: [...(chart?.querySelectorAll('.col') ?? [])].map(box),
      ranges: [...(chart?.querySelectorAll('.range') ?? [])].map(box),
      times: [...(chart?.querySelectorAll('.time') ?? [])].map(box),
      words: [...(chart?.querySelectorAll('.words') ?? [])].map(box),
      // Each dashed line, and the words that are not its own.
      lines: [...(chart?.querySelectorAll('.line') ?? [])].map((line) => ({
        ...box(line),
        others: [...(chart?.querySelectorAll('.words') ?? [])]
          .filter((words) => !line.classList.contains(words.classList[1] ?? ''))
          .map(box),
      })),
      rows: [...(chart?.querySelectorAll('.key .row') ?? [])].map((row) => ({
        ...box(row),
        cut: row.scrollWidth > row.clientWidth,
      })),
      scrolls: body.scrollWidth > body.clientWidth,
    };
  });
  const { panel, plot, bars, ranges, times, words, rows, lines } = layout;
  // A dashed line runs clear of the other line's words.
  lines.forEach((line, i) => {
    for (const other of line.others) {
      expect(overlaps(line, other), `${label}: line ${String(i)} and other words`).toBe(false);
    }
  });
  if (plot === null) throw new Error(`${label}: no chart`);
  expect(bars.length, label).toBeGreaterThan(1);
  for (const bar of bars) expect(bar.width, `${label}: a bar`).toBeGreaterThanOrEqual(3);
  // The answer, and the announcement's words where it falls in the night drawn.
  expect(words.length, label).toBeGreaterThan(0);
  words.forEach((word, i) => {
    expect(word.x, `${label}: words ${String(i)}`).toBeGreaterThanOrEqual(plot.x - 0.5);
    expect(word.x + word.width, `${label}: words ${String(i)}`).toBeLessThanOrEqual(
      plot.x + plot.width + 0.5,
    );
    for (const mark of [...bars, ...ranges, ...times]) {
      expect(overlaps(word, mark), `${label}: words ${String(i)} and a bar, range or time`).toBe(
        false,
      );
    }
    words.slice(i + 1).forEach((other, j) => {
      expect(overlaps(word, other), `${label}: words ${String(i)}, ${String(i + 1 + j)}`).toBe(
        false,
      );
    });
  });
  times.forEach((time, i) => {
    expect(time.x, `${label}: time ${String(i)}`).toBeGreaterThanOrEqual(plot.x - 0.5);
    expect(time.x + time.width, `${label}: time ${String(i)}`).toBeLessThanOrEqual(
      plot.x + plot.width + 0.5,
    );
    times.slice(i + 1).forEach((other, j) => {
      expect(overlaps(time, other), `${label}: times ${String(i)}, ${String(i + 1 + j)}`).toBe(
        false,
      );
    });
  });
  rows.forEach((row, i) => {
    expect(row.cut, `${label}: key row ${String(i)} cut off`).toBe(false);
    expect(row.x, `${label}: key row ${String(i)}`).toBeGreaterThanOrEqual(panel.x);
    expect(row.x + row.width, `${label}: key row ${String(i)}`).toBeLessThanOrEqual(
      panel.x + panel.width,
    );
    for (const time of times) {
      expect(overlaps(row, time), `${label}: key row ${String(i)} and a time`).toBe(false);
    }
    rows.slice(i + 1).forEach((other, j) => {
      expect(overlaps(row, other), `${label}: key rows ${String(i)}, ${String(i + 1 + j)}`).toBe(
        false,
      );
    });
  });
  expect(layout.scrolls, `${label}: the panel scrolls sideways`).toBe(false);
}

/** The words a part of the page shows, as one line; what only a screen reader reads, or none, left out. */
async function shownText(part: Locator): Promise<string> {
  return part.evaluate((root) => {
    const words: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (parent?.closest('.sr-only') !== null) continue;
      if (getComputedStyle(parent).visibility === 'hidden') continue;
      words.push(node.textContent ?? '');
    }
    return words.join(' ').replace(/\s+/gu, ' ');
  });
}

/** Whether two boxes on the page overlap. */
function overlaps(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
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

/** How brightly the key at the foot of the screen draws each status's mark, in code order. */
async function keyMarks(page: Page): Promise<number[]> {
  return page
    .locator('ul.legend .glyph')
    .evaluateAll((marks) => marks.map((mark) => Number(getComputedStyle(mark).opacity)));
}

/** Whether the menu's button carries its dot: the map shows less than everything. */
async function filteredDot(page: Page): Promise<boolean> {
  return page
    .locator('button.menu-button')
    .evaluate((button) => getComputedStyle(button, '::before').content !== 'none');
}

/** Where the menu's rows put things, in px from the panel's left edge, each as the distinct values found. */
interface MenuGrid {
  /** Each row's height. */
  heights: number[];
  /** Each row's 16px icon: its left edge, width and height. */
  icons: number[];
  iconSizes: string[];
  /** Where each row's name starts, and each line and label on a page. */
  names: number[];
  /** Where each row's count, arrow or value ends. */
  ends: number[];
  /** Where each heading's words start. */
  headings: number[];
  /** The pill around the row in use: its corner radius against its height, and whether it is filled. */
  pills: string[];
}

async function menuGrid(menu: Locator): Promise<MenuGrid> {
  return menu.evaluate((panel) => {
    const origin = panel.getBoundingClientRect().left;
    const at = (value: number): number => Math.round((value - origin) * 2) / 2;
    const words = (element: Element): DOMRect | null => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const rect = range.getBoundingClientRect();
      return rect.width > 0 ? rect : null;
    };
    const distinct = <T>(values: T[]): T[] => [...new Set(values)];
    const rows = [...panel.querySelectorAll('.item, .row')];
    const icons = rows
      .map((row) => row.querySelector('.icon'))
      .filter((icon) => icon !== null)
      .map((icon) => icon.getBoundingClientRect());
    const names = [
      ...panel.querySelectorAll(
        '.item .name, .line, dt, .record tbody th, .record thead th:first-child',
      ),
    ]
      .map((element) => {
        // A label on a page starts after the mark in its icon column.
        const text = element.matches('dt') ? element.lastChild : element;
        if (text === null) return null;
        const range = document.createRange();
        range.selectNodeContents(text);
        if (text.nodeType === Node.TEXT_NODE) {
          const content = text.textContent ?? '';
          range.setStart(text, content.length - content.trimStart().length);
        }
        const rect = range.getBoundingClientRect();
        return rect.width > 0 ? rect.left : null;
      })
      .filter((left) => left !== null);
    const ends = [...panel.querySelectorAll('.value, .more, dd, .record td:last-child')]
      .map((element) =>
        element.matches('.more') ? element.getBoundingClientRect() : words(element),
      )
      .filter((rect) => rect !== null)
      .map((rect) => at(rect.right));
    // Layout can land a size a hair off a whole pixel on CI's GPU-less Chromium (a row of
    // 40.000015, an icon 15.999985 tall).
    const px = (value: number): number => Math.round(value * 100) / 100;
    const pills = [...panel.querySelectorAll('.item.is-on')].map((row) => {
      const style = getComputedStyle(row);
      return `${style.borderTopLeftRadius} of ${String(px(row.getBoundingClientRect().height))}, ${style.backgroundColor}`;
    });
    return {
      heights: distinct(
        rows
          .filter((row) => row.matches('.item'))
          .map((row) => px(row.getBoundingClientRect().height)),
      ),
      icons: distinct(icons.map((rect) => at(rect.left))),
      iconSizes: distinct(
        icons.map((rect) => `${String(px(rect.width))}x${String(px(rect.height))}`),
      ),
      names: distinct(names.map(at)),
      ends: distinct(ends),
      headings: distinct(
        [...panel.querySelectorAll('h2.label')]
          .map(words)
          .filter((rect) => rect !== null)
          .map((rect) => at(rect.left)),
      ),
      pills,
    };
  });
}

/** Waits out the menu's arrival (it slides 4px down as it fades in), so its box is where it rests. */
async function arrived(menu: Locator): Promise<void> {
  await menu.evaluate(async (panel) => {
    await Promise.all(panel.getAnimations().map((animation) => animation.finished));
  });
}

/**
 * The menu's one grid: every row the same height, its 16px icon in one column and its name in
 * one column 28px after it, the headings' words over the icons, and every count, arrow or value
 * ending at one right edge; the row in use on a filled pill as round as the row is tall.
 */
async function expectMenuGrid(menu: Locator, row: number, where: string): Promise<void> {
  const grid = await menuGrid(menu);
  expect(grid.heights, where).toEqual([row]);
  expect(grid.iconSizes, where).toEqual(['16x16']);
  expect(grid.icons, where).toHaveLength(1);
  const [icon = 0] = grid.icons;
  expect(grid.names, where).toEqual([icon + 28]);
  expect(grid.headings, where).toEqual([icon]);
  expect(grid.ends, where).toHaveLength(1);
  expect(grid.pills.length, where).toBeLessThanOrEqual(1);
  for (const pill of grid.pills) {
    expect(pill, where).toMatch(
      new RegExp(`^${String(row / 2)}px of ${String(row)}, rgb\\(42, 42, 42\\)$`, 'u'),
    );
  }
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
    mkdirSync(path.join(data, 'stats'), { recursive: true });
    writeFileSync(path.join(data, 'stats/season.json'), syntheticSeason());
    writeFileSync(path.join(data, 'track-record.json'), syntheticTrackRecord());
    mkdirSync(path.join(data, 'predictions'), { recursive: true });
    writeFileSync(path.join(data, 'predictions/latest.json'), syntheticPredictions());
    mkdirSync(path.join(data, 'schools/details'), { recursive: true });
    const details = directoryDetails();
    writeFileSync(path.join(data, 'schools/details/index.json'), details.index);
    writeFileSync(path.join(data, 'schools/details/0.json'), details.shard);
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
      'predictions/latest.json',
      'schools/details/0.json',
      'schools/details/index.json',
      'schools/meta.json',
      'schools/points.bin',
      'search-index.bin',
      'stats/season.json',
      'track-record.json',
    ]);
    expect(statSync(path.join(root, 'site', 'data', 'search-index.bin')).size).toBeGreaterThan(0);
  });

  test('the menu counts today’s schools, and opens the season, the track record and About from their files', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.clock.setFixedTime(SYNTHETIC_NOW);
    const { problems, requests } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    await expect.poll(async () => (await glowStats(page)).glowCount, { timeout: 30_000 }).toBe(2);
    await page.getByRole('button', { name: copy.menu.label, exact: true }).click();
    const menu = page.locator('aside.menu');
    await expect(menu).toBeVisible();
    await arrived(menu);
    await expect(menu.locator('h2')).toHaveText([copy.menu.today, copy.menu.kinds]);
    // Today's schools as the live file lights them: one closed, one delayed.
    const counted = async (): Promise<string[][]> =>
      menu
        .locator('.item')
        .evaluateAll((found) =>
          found.map((item) =>
            [item.querySelector('.name'), item.querySelector('.value')].map(
              (cell) => cell?.textContent.trim() ?? '',
            ),
          ),
        );
    expect(await counted()).toEqual([
      [copy.menu.all, format.number(2)],
      [copy.status.closed, format.number(1)],
      [copy.status.delayed, format.number(1)],
      [copy.status.remote, ''],
      [copy.status.earlyDismissal, ''],
      [copy.menu.public, ''],
      [copy.menu.private, ''],
      [copy.nav.seasonStats, ''],
      [copy.nav.trackRecord, ''],
      [copy.nav.about, ''],
    ]);
    await expectMenuGrid(menu, 40, 'list');
    const panel = await menu.boundingBox();
    if (panel === null) throw new Error('no box');
    const list = await menuGrid(menu);

    /** The rows of the page open: each label and its value (a table's cells in order). */
    const rows = async (): Promise<string[][]> =>
      menu
        .locator('.row, tr')
        .evaluateAll((found) =>
          found.map((row) =>
            [...row.children].map((cell) => cell.textContent.replace(/\s+/gu, ' ').trim()),
          ),
        );
    const back = menu.getByRole('button', { name: copy.detail.back, exact: true });

    // The season as its file counts it: two schools, one district, three school-days.
    await menu.getByRole('button', { name: copy.nav.seasonStats }).click();
    await expect(back).toBeFocused();
    await expect(menu.locator('.title')).toHaveText(copy.nav.seasonStats);
    await expect(menu.locator('.note')).toHaveText([
      `${format.season('2025-2026')} · ${format.through('2026-01-12')}`,
    ]);
    expect(await rows()).toEqual([
      [copy.season.schoolsAffected, '2'],
      [copy.season.districtsAffected, '1'],
      [copy.season.closures, '2'],
      [copy.season.delays, '1'],
      [copy.season.busiestDay, `${format.day('2026-01-12')} · ${format.schools(2)}`],
    ]);
    // On the list's grid: the labels in its text column, the values ending where its counts do.
    const season = await menuGrid(menu);
    expect(season.names).toEqual(list.names);
    expect(season.ends).toEqual(list.ends);
    await back.click();
    await expect(menu.getByRole('button', { name: copy.nav.seasonStats })).toBeFocused();

    // The track record: of the 4 days given 80–90% the day before, 3 had no school.
    await menu.getByRole('button', { name: copy.nav.trackRecord }).click();
    await expect(menu.locator('.title')).toHaveText(copy.nav.trackRecord);
    await expect(menu.locator('.note')).toHaveText([format.span('2026-01-05', '2026-01-12')]);
    await expect(menu.locator('caption')).toHaveText(copy.trackRecord.caption);
    expect(await rows()).toEqual([
      [copy.trackRecord.chanceGiven, format.lead(1)],
      [format.percentRange(80, 90), format.outOf(3, 4)],
    ]);
    const record = await menuGrid(menu);
    expect(record.names).toEqual(list.names);
    expect(record.ends).toEqual(list.ends);
    await back.click();

    // About: what the site is, then what the map holds: the directory's five schools (Border Star
    // and Pembroke Hill, and the three the chance section needs) in four districts.
    await menu.getByRole('button', { name: copy.nav.about }).click();
    await expect(menu.locator('.lead')).toHaveText(copy.about.what);
    await expect(menu.locator('.note')).toHaveText([copy.menu.onMap]);
    expect(await rows()).toEqual([
      [copy.menu.schools, '5'],
      [copy.menu.districts, '4'],
    ]);
    const about = await menuGrid(menu);
    expect(about.names).toEqual(list.names);
    expect(about.ends).toEqual(list.ends);

    for (const file of ['stats/season.json', 'track-record.json', 'schools/details/index.json']) {
      expect(
        requests.some((url) => url.endsWith(`/data/${file}`)),
        file,
      ).toBe(true);
    }
    // Every page in the same place, no wider, and nothing on the page moved as it opened.
    const after = await menu.boundingBox();
    expect([after?.x, after?.y, after?.width]).toEqual([panel.x, panel.y, panel.width]);
    expect(await layoutShifts(page)).toEqual([]);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the menu shows one status or all four, and public schools, private ones or both', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    await page.clock.setFixedTime(SYNTHETIC_NOW);
    const { problems } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    const lit = async (): Promise<number> => (await glowStats(page)).glowCount;
    await expect.poll(lit, { timeout: 30_000 }).toBe(2);
    const button = page.getByRole('button', { name: copy.menu.label, exact: true });
    await button.click();
    const menu = page.locator('aside.menu');
    await expect(menu).toBeVisible();
    const legend = page.locator('ul.legend');
    /** Presses a kind's row, as a person does, and checks its box took the press. */
    const toggle = async (name: string, shown: boolean): Promise<void> => {
      await menu.locator('label.item', { hasText: name }).click();
      const box = menu.getByRole('checkbox', { name });
      await (shown ? expect(box).toBeChecked() : expect(box).not.toBeChecked());
    };

    // Closed alone: Border Star lights, Pembroke Hill (delayed) does not; the key steps back
    // from the other statuses, and the counts stay, so each status says what it would show.
    await menu.locator('label.item', { hasText: copy.status.closed }).click();
    await expect.poll(lit).toBe(1);
    await expect(menu.getByRole('radio', { name: copy.status.closed })).toBeChecked();
    await expect(menu.locator('.item.is-on .name')).toHaveText([copy.status.closed]);
    await expect(page.locator('main.stage')).toHaveAttribute('data-status', '0');
    // Remote and early dismissal have none today, and step back as they did.
    await expect.poll(() => keyMarks(page)).toEqual([1, 0.4, 0.4, 0.4]);
    await expect(legend.locator('li')).toHaveText([
      `${copy.status.closed} ${format.number(1)}`,
      `${copy.status.delayed} ${format.number(1)}`,
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    await expect.poll(() => filteredDot(page)).toBe(true);
    // The keyboard moves the choice along, as a radio group's arrows do.
    await page.keyboard.press('ArrowDown');
    await expect(menu.getByRole('radio', { name: copy.status.delayed })).toBeChecked();
    await expect.poll(lit).toBe(1);
    await menu.locator('label.item', { hasText: copy.menu.all }).click();
    await expect.poll(lit).toBe(2);
    await expect(page.locator('main.stage')).not.toHaveAttribute('data-status');
    await expect.poll(() => keyMarks(page)).toEqual([1, 1, 0.4, 0.4]);

    // Public schools alone: Pembroke Hill is private, so only Border Star lights; the counts are
    // of public schools. (This build has no school tiles: e2e/real-data.spec.ts checks the dots.)
    await toggle(copy.menu.private, false);
    await expect.poll(lit).toBe(1);
    await expect(legend.locator('.count')).toHaveText([format.number(1)]);
    await expect(menu.locator('.item').first().locator('.value')).toHaveText(format.number(1));
    await expect.poll(() => filteredDot(page)).toBe(true);
    // Private alone: Pembroke Hill.
    await toggle(copy.menu.public, false);
    await toggle(copy.menu.private, true);
    await expect.poll(lit).toBe(1);
    await expect(legend.locator('li')).toHaveText([
      copy.status.closed,
      `${copy.status.delayed} ${format.number(1)}`,
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    // Both again: everything, as it opened.
    await toggle(copy.menu.public, true);
    await expect.poll(lit).toBe(2);
    await expect.poll(() => filteredDot(page)).toBe(false);
    await expect(legend.locator('.count')).toHaveText([format.number(1), format.number(1)]);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('search loads the index on first focus, lists results, and a pick takes the map there', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const { problems, requests } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    // A data file the page loads before the service worker takes over is fetched once more,
    // through the worker, for offline use (src/pwa/data.ts warmDataCache): search starts here
    // once the worker is in control, so the index is fetched once, through it.
    await page.evaluate(async () => {
      const worker = (
        window as unknown as {
          snowlightServiceWorker?: Promise<{ warmed: Promise<number> } | null>;
        }
      ).snowlightServiceWorker;
      await (
        await worker
      )?.warmed;
    });
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

  test('a picked school lands in its panel: its day from the live file, what it is, pin, share and close', async ({
    browser,
  }) => {
    // Two first flights into streets, one a page (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: 'America/Chicago',
      permissions: ['clipboard-read', 'clipboard-write'],
    });
    const page = await context.newPage();
    // Its calendar alone: the flights below and the share button's timer run in real time.
    await fixDate(page, SYNTHETIC_NOW);
    const { problems } = watch(page);
    await page.goto(site);
    await waitForMap(page);
    const input = page.locator('input.search-input');
    await input.click();
    await input.pressSequentially('pembroke', { delay: 20 });
    await page.locator('[role="option"]').first().click();

    const panel = page.locator('aside.detail');
    await expect(panel).toHaveAccessibleName(copy.detail.label);
    await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect(panel.locator('.kind')).toHaveText(`${copy.detail.privateSchool} · PK–12`);
    await expect(panel.locator('.place')).toHaveText('Kansas City, MO · Jackson County');
    // SYNTHETIC statuses: delayed today, as the made-up live file says, and nothing made up here.
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.delayed.today]);
    await expect(panel.locator('.status .line-detail')).toHaveText(format.delay(120, null) ?? '');
    await expect(panel.locator('.status .line-note')).toHaveText(
      `${copy.reason.ice} · ${format.posted(new Date('2026-01-12T12:02:00Z'), 'America/Chicago', SYNTHETIC_NOW)}`,
    );
    await expect(panel.locator('.status .glyph.is-delayed')).toHaveCount(1);
    // A private school has no district history to give a chance: there is no chance card.
    await expect(panel.locator('.outlook')).toHaveCount(0);
    await expect(panel.locator('.chance')).toHaveCount(0);
    await expect(panel.locator('.fact dt')).toHaveText([
      copy.detail.students,
      copy.detail.address,
      copy.detail.phone,
    ]);
    await expect(panel.locator('.fact a')).toHaveAttribute('href', 'tel:+18169361230');
    // The school nearest it, keyed with its status today (SYNTHETIC: closed).
    await expect(panel.locator('.near-name')).toHaveText(['Border Star Montessori']);
    await expect(panel.locator('.near-distance')).toHaveText([format.miles(2530)]);
    await expect(panel.locator('.near .glyph.is-closed')).toHaveCount(1);
    // After a pick the panel has the focus.
    await expect(panel).toBeFocused();
    // The map lands on the school: the share button's timer below then runs on a page at rest.
    await expectMapNear(page, 39.03606, -94.593001, 15, FIRST_FLIGHT_MS);

    const [pin, share] = [panel.locator('.action').nth(0), panel.locator('.action').nth(1)];
    await pin.click();
    await expect(pin).toHaveAttribute('aria-pressed', 'true');
    await expect(pin).toHaveText(copy.pin.mySchool);
    expect(await page.evaluate((key) => localStorage.getItem(key), PIN_KEY)).toBe(
      JSON.stringify({ v: 1, school: PEMBROKE_HILL }),
    );
    await share.click();
    await expect(share).toHaveText(copy.share.copied);
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      `${site}?school=${PEMBROKE_HILL}`,
    );
    // Back to Share once the button's own time is up, with a moment's slack for a busy page.
    await expect(share).toHaveText(copy.actions.share, { timeout: COPIED_MS + 3000 });

    // Escape closes it: the school leaves the address.
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();

    // A link to a public school opens its panel too: closed today, with its district.
    await page.goto(`${site}?school=291640000557`);
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.closed.today]);
    await expect(panel.locator('.status .glyph.is-closed')).toHaveCount(1);
    await expect(panel.locator('.fact dt').first()).toHaveText(copy.detail.district);
    await expect(panel.locator('.fact dd').first()).toHaveText('Kansas City 33');
    // It lands there first, as a link does: the nearby school below is picked from its streets.
    await expectMapNear(page, 39.013304, -94.592692, 15, FIRST_FLIGHT_MS);
    // Its nearest school opens from the list: the map goes there, and its panel takes this one's place.
    await panel.locator('.near').first().click();
    await expect(panel.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe(PEMBROKE_HILL);
    await expectMapNear(page, 39.03606, -94.593001, 15);
    await panel.locator('.close').click();
    await expect(panel).toHaveCount(0);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the chance section, the night before: the chance first, the evening, the night, and how it adds up', async ({
    browser,
  }) => {
    // A first flight into streets (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: ZONE,
      // The evening's live file comes from the route below, not a worker's cache.
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    await fixDate(page, EVENING);
    const { problems } = watch(page);
    await page.route('**/data/live/closings.json*', (route) =>
      route.fulfill({ contentType: 'application/json', body: syntheticEveningClosings() }),
    );
    await page.goto(`${site}?school=${SHAWNEE_MISSION_EAST}`);
    const panel = page.locator('aside.detail');
    const section = panel.locator('.chance');
    await expect(panel.locator('h2')).toHaveText('Shawnee Mission East High');

    // The chance is the headline, for Tuesday, with what moved it.
    await expect(section.locator('.number')).toHaveText('64%', { timeout: 60_000 });
    await expect(section.locator('.meaning')).toContainText(chanceFormat.chanceOn('2026-01-13'));
    await expect(section.locator('.change')).toHaveText(
      chanceFormat.moved({
        previous: 0.41,
        current: 0.64,
        at: new Date('2026-01-12T23:00:00Z'),
        now: EVENING,
        zones: { school: ZONE, viewer: ZONE },
      }) ?? '',
    );
    // No status is posted for this school yet: none above the chance.
    await expect(section.locator('.status')).toHaveCount(0);

    // The districts next door that canceled, from the live file; when this one announces is
    // the chart's to say.
    await expect(section.locator('.moment')).toHaveText([
      `${format.time(new Date('2026-01-13T02:41:00Z'), ZONE)} Blue Valley canceled Tuesday`,
      `${format.time(new Date('2026-01-13T02:52:00Z'), ZONE)} Olathe canceled Tuesday`,
    ]);

    // The chart: a bar an hour, the heaviest lit, the buses and the range at their hour; over
    // it the two dashed lines' words, the answer first, and under it the lit bars' key row.
    const chart = section.locator('.chart');
    const zones = { school: ZONE, viewer: ZONE };
    await expect(chart.locator('figcaption')).toHaveText(chanceCopy.snowTitle);
    await expect(chart.locator('.col')).toHaveCount(11);
    // The heaviest snow, 2 to 5 AM, is the 3, 4 and 5 AM bars' growth: three lit.
    await expect(chart.locator('.col.is-lit')).toHaveCount(3);
    await expect(chart.locator('.range')).toHaveCount(1);
    await expect(chart.locator('.line')).toHaveCount(2);
    const buses = chanceFormat.busesKey(
      chanceFormat.inches(6, 9),
      new Date('2026-01-13T13:00:00Z'),
      zones,
    );
    await expect(chart.locator('.words')).toHaveText([
      `${buses.value}${buses.rest}`,
      chanceFormat.announcesKey(new Date('2026-01-13T11:30:00Z'), zones, EVENING),
    ]);
    await expect(chart.locator('.words .value')).toHaveText(chanceFormat.inches(6, 9));
    await expect(chart.locator('.key .row')).toHaveText([
      chanceFormat.heaviestKey(
        new Date('2026-01-13T08:00:00Z'),
        new Date('2026-01-13T11:00:00Z'),
        zones,
      ),
    ]);
    // The 460 px panel has room for the heaviest snow's end, 5 AM, under its last lit bar.
    await expect(chart.locator('.time')).toHaveText([
      chanceCopy.now,
      ...['2026-01-13T05:00:00Z', '2026-01-13T11:00:00Z', '2026-01-13T13:00:00Z'].map((iso) =>
        chanceFormat.clock(new Date(iso), zones),
      ),
    ]);
    // Laid out, no words meet, none meets a bar or the range, and all are in the panel.
    const boxes = async (selector: string) =>
      (await chart.locator(selector).evaluateAll((nodes) =>
        nodes.map((node) => {
          const { x, y, width, height } = node.getBoundingClientRect();
          return { x, y, width, height };
        }),
      )) as { x: number; y: number; width: number; height: number }[];
    const panelBox = await panel.boundingBox();
    if (panelBox === null) throw new Error('no panel');
    const words = [
      ...(await boxes('.time')),
      ...(await boxes('.words')),
      ...(await boxes('.key .row')),
    ];
    words.forEach((box, i) => {
      words.slice(i + 1).forEach((other, j) => {
        expect(overlaps(box, other), `words ${String(i)} and ${String(i + 1 + j)}`).toBe(false);
      });
      expect(box.x).toBeGreaterThanOrEqual(panelBox.x);
      expect(box.x + box.width).toBeLessThanOrEqual(panelBox.x + panelBox.width);
    });
    const bars = await boxes('.col, .range');
    for (const box of words) {
      for (const bar of bars) expect(overlaps(box, bar)).toBe(false);
    }

    // How it adds up, always open: the base and each reason's points, adding up to the headline.
    await expect(section.locator('.why-title')).toHaveText(chanceFormat.howWeGot(0.64));
    const rows = section.locator('.sum > li');
    await expect(rows).toHaveCount(6);
    // Each reason names itself: its numbers are the chart's, and who canceled is the timeline's.
    await expect(rows.nth(1)).toHaveText(
      '+16 More snow than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
    );
    await expect(rows.nth(2)).toHaveText('+9 Districts next door canceled.');
    await expect(rows.nth(3)).toHaveText('+7 Heaviest snow just before the buses.');
    // Nothing said twice in the section as it shows.
    const shown = await shownText(section);
    for (const fact of ['6 to 9', '2 to 5', '5:30', 'Blue Valley', 'Olathe', 'announces']) {
      expect(shown.split(fact).length - 1, fact).toBe(1);
    }
    const numbers = (await section.locator('.sum .num').allTextContents()).map((text) =>
      Number(text.replace('−', '-')),
    );
    expect(numbers.reduce((sum, n) => sum + n, 0)).toBe(64);
    await expect(section.locator('details, [aria-expanded="false"]')).toHaveCount(0);
    await expect(section.locator('.delay')).toHaveText(chanceFormat.delayInstead(0.18));

    // Wider beside the map on a wide screen, so the chart is bigger: 460 px, 420 px, then 368.
    expect(panelBox.width).toBeCloseTo(460, 0);
    await page.setViewportSize({ width: 1100, height: 900 });
    await expect.poll(async () => (await panel.boundingBox())?.width).toBeCloseTo(420, 0);
    await page.setViewportSize({ width: 900, height: 900 });
    await expect.poll(async () => (await panel.boundingBox())?.width).toBeCloseTo(368, 0);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the chance section for a viewer in New York: each time the school’s, its zone under it, clear of its words, at 1440 and 320 px', async ({
    browser,
  }) => {
    // A first flight into streets (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: 'America/New_York',
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    await fixDate(page, EVENING);
    const { problems } = watch(page);
    await page.route('**/data/live/closings.json*', (route) =>
      route.fulfill({ contentType: 'application/json', body: syntheticEveningClosings() }),
    );
    await page.goto(`${site}?school=${SHAWNEE_MISSION_EAST}`);
    const panel = page.locator('aside.detail');
    const section = panel.locator('.chance');
    await expect(section.locator('.number')).toHaveText('64%', { timeout: 60_000 });
    await expect(section.locator('.moment .label')).toHaveText([
      /^8:41\sPM CT$/u,
      /^8:52\sPM CT$/u,
    ]);
    for (const width of [1440, 320]) {
      await page.setViewportSize({ width, height: width === 1440 ? 900 : 844 });
      // The time's own words, however they wrap, end before the moment's words start.
      const rows = await section.locator('.moment').evaluateAll((nodes) =>
        nodes.map((node) => {
          const extent = (part: Element | undefined) => {
            const range = document.createRange();
            if (part !== undefined) range.selectNodeContents(part);
            const { x, y, width, height } = range.getBoundingClientRect();
            return { x, y, width, height };
          };
          return { time: extent(node.children[0]), words: extent(node.children[1]) };
        }),
      );
      expect(rows).toHaveLength(2);
      for (const [i, { time, words }] of rows.entries()) {
        const label = `${String(width)} px, moment ${String(i)}`;
        expect(time.width, label).toBeGreaterThan(0);
        expect(overlaps(time, words), label).toBe(false);
        expect(time.x + time.width, label).toBeLessThanOrEqual(words.x);
      }
    }
    expect(
      problems.filter((line) => !line.includes('Service Worker registration blocked')),
    ).toEqual([]);
    await context.close();
  });

  test('the chance section on a phone: in the sheet, the chance above the fold, all of it in the sheet’s width', async ({
    browser,
  }) => {
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
      timezoneId: ZONE,
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    await fixDate(page, EVENING);
    const { problems } = watch(page);
    await page.route('**/data/live/closings.json*', (route) =>
      route.fulfill({ contentType: 'application/json', body: syntheticEveningClosings() }),
    );
    await page.goto(`${site}?school=${SHAWNEE_MISSION_EAST}`);
    const sheet = page.locator('aside.detail');
    const section = sheet.locator('.chance');
    await expect(section.locator('.number')).toHaveText('64%', { timeout: 60_000 });
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    // Open part way, the sheet shows the chance, before the buttons.
    await expect.poll(async () => (await sheet.boundingBox())?.y).toBeCloseTo(844 - 422, 0);
    const hero = await section.locator('.hero').boundingBox();
    expect((hero?.y ?? 844) + (hero?.height ?? 0)).toBeLessThan(844);
    const actions = await sheet.locator('.actions').boundingBox();
    expect(actions?.y).toBeGreaterThan((hero?.y ?? 0) + (hero?.height ?? 0));
    // Up to full height, then down to the sum: every part of the section inside the sheet.
    await sheet.locator('.grip').tap();
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    for (const part of ['.delay', '.moments', '.chart', '.why']) {
      const node = section.locator(part);
      await node.scrollIntoViewIfNeeded();
      const box = await node.boundingBox();
      if (box === null) throw new Error(`no ${part}`);
      expect(box.x, part).toBeGreaterThanOrEqual(16);
      expect(box.x + box.width, part).toBeLessThanOrEqual(390 - 16 + 0.5);
      expect(box.y, part).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height, part).toBeLessThanOrEqual(844);
    }
    // The chart's words stay in the sheet too, and nothing scrolls sideways.
    const end = await section.locator('.chart .time.is-end').boundingBox();
    expect((end?.x ?? 0) + (end?.width ?? 0)).toBeLessThanOrEqual(390);
    expect(
      await sheet.locator('.body').evaluate((body) => body.scrollWidth <= body.clientWidth),
    ).toBe(true);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the chance section the evening of a closed day: the status first, then tomorrow’s chance and its cold night', async ({
    browser,
  }) => {
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: ZONE,
    });
    const page = await context.newPage();
    await fixDate(page, EVENING);
    const { problems } = watch(page);
    // The staged live file, from that morning: Border Star closed Monday.
    await page.goto(`${site}?school=291640000557`);
    const panel = page.locator('aside.detail');
    const section = panel.locator('.chance');
    await expect(section.locator('.number')).toHaveText('22%', { timeout: 60_000 });
    await expect(section.locator('.status .headline')).toHaveText([copy.statusLine.closed.today]);
    await expect(section.locator('.status .glyph.is-closed')).toHaveCount(1);
    const status = await section.locator('.status').boundingBox();
    const hero = await section.locator('.hero').boundingBox();
    expect((status?.y ?? 0) + (status?.height ?? 0)).toBeLessThanOrEqual(hero?.y ?? 0);
    await expect(section.locator('.meaning')).toContainText(chanceFormat.chanceOn('2026-01-13'));
    await expect(section.locator('.change')).toHaveText(
      chanceFormat.moved({
        previous: 0.3,
        current: 0.22,
        at: new Date('2026-01-12T15:00:00Z'),
        now: EVENING,
        zones: { school: ZONE, viewer: ZONE },
      }) ?? '',
    );
    await expect(section.locator('.moment')).toHaveText([
      `${format.time(new Date('2026-01-12T12:00:00Z'), ZONE)} Snow stopped, 8 inches in all`,
    ]);
    await expect(section.locator('.chart .words.is-announces')).toHaveText(
      chanceFormat.announcesKey(
        new Date('2026-01-13T11:30:00Z'),
        { school: ZONE, viewer: ZONE },
        EVENING,
      ),
    );
    // How cold, and when the snow stopped, are the chart's and the timeline's.
    await expect(section.locator('.sum > li').nth(1)).toHaveText(
      '−8 The snow stopped, a full day for the plows.',
    );
    await expect(section.locator('.sum > li').nth(2)).toHaveText(
      '+6 Cold at the bus stop Tuesday morning.',
    );
    const chart = section.locator('.chart');
    await expect(chart.locator('figcaption')).toHaveText(chanceCopy.coldTonight);
    await expect(chart.locator('.col.is-below')).toHaveCount(11);
    await expect(chart.locator('.words .value')).toHaveText(chanceFormat.degrees(-8));
    await expect(chart.locator('.key')).toHaveCount(0);
    const numbers = (await section.locator('.sum .num').allTextContents()).map((text) =>
      Number(text.replace('−', '-')),
    );
    expect(numbers.reduce((sum, n) => sum + n, 0)).toBe(22);
    await expect(section.locator('.delay')).toHaveText(chanceFormat.delayInstead(0.31));
    // The rest of the panel is as it was: the district, and no chance card of the old kind.
    await expect(panel.locator('.fact dd').first()).toHaveText('Kansas City 33');
    await expect(panel.locator('.outlook')).toHaveCount(0);
    expect(problems).toEqual([]);
    await context.close();
  });

  test('the chance chart at 320, 390 and 460 px: for nights long and short, its words fit and none meet', async ({
    browser,
  }) => {
    // Three first flights into streets, and five nights at each width.
    test.setTimeout(720_000);
    const layouts = [
      { phone: true, widths: [320, 390], viewer: ZONE },
      // The panel beside the map on a wide screen: 460 px.
      { phone: false, widths: [1440], viewer: ZONE },
      // A viewer in New York: every time the school's, with "CT" after it, at the narrowest.
      { phone: true, widths: [320], viewer: 'America/New_York' },
    ];
    for (const { phone, widths, viewer } of layouts) {
      const height = phone ? 844 : 900;
      const context = await browser.newContext({
        viewport: { width: widths[0] ?? 390, height },
        ...(phone ? { deviceScaleFactor: 2, isMobile: true, hasTouch: true } : {}),
        timezoneId: viewer,
        serviceWorkers: 'block',
      });
      const page = await context.newPage();
      await fixDate(page, SHAPE_NOW);
      const { problems } = watch(page);
      let body = '';
      await page.route('**/data/predictions/latest.json*', (route) =>
        route.fulfill({ contentType: 'application/json', body }),
      );
      const panel = page.locator('aside.detail');
      const chart = panel.locator('.chance .chart');
      for (const [i, shape] of NIGHT_SHAPES.entries()) {
        body = shapedPredictions(shape);
        await page.setViewportSize({ width: widths[0] ?? 390, height });
        if (i === 0) {
          await page.goto(`${site}?school=${SHAWNEE_MISSION_EAST}`);
        } else {
          await showSchool(page, null);
          await expect(panel).toHaveCount(0);
          await showSchool(page, SHAWNEE_MISSION_EAST);
        }
        const last = shape.values.at(-1) ?? 0;
        const value =
          shape.range !== null
            ? chanceFormat.inches(shape.range[0], shape.range[1])
            : shape.kind === 'snow_total'
              ? chanceFormat.inches(last)
              : chanceFormat.degrees(last);
        await expect(chart.locator('.words .value'), shape.name).toHaveText(value, {
          timeout: 60_000,
        });
        await expect(chart.locator('.col'), shape.name).toHaveCount(shape.bars);
        // The heaviest hours' key row on a snowy night; none on a cold one.
        await expect(chart.locator('.key .row'), shape.name).toHaveCount(
          shape.heavy === null ? 0 : 1,
        );
        if (viewer !== ZONE) {
          await expect(chart.locator('.time.is-end'), shape.name).toHaveText(/\sCT$/u);
        }
        for (const width of widths) {
          await page.setViewportSize({ width, height });
          const panelWidth = phone ? width : 460;
          await expect
            .poll(async () => (await panel.boundingBox())?.width)
            .toBeCloseTo(panelWidth, 0);
          await expectChartFits(page, `${shape.name}, ${String(panelWidth)} px, ${viewer}`);
        }
      }
      // With workers blocked (so each night comes from the route), the app says so once it
      // tries to register its own; nothing else.
      expect(
        problems.filter((line) => !line.includes('Service Worker registration blocked')),
      ).toEqual([]);
      await context.close();
    }
  });

  test('on a phone a school opens in a sheet half up, over the map with the school in the middle of what it leaves, and the sheet drags', async ({
    browser,
  }) => {
    const context = await browser.newContext({
      ...devices['Pixel 7'],
      timezoneId: 'America/Chicago',
    });
    const page = await context.newPage();
    const { problems } = watch(page);
    const touch = await context.newCDPSession(page);
    /** A finger put down at (x, from), moved to (x, to) over `ms`, and lifted. */
    const drag = async (x: number, from: number, to: number, ms: number): Promise<void> => {
      await touch.send('Input.dispatchTouchEvent', {
        type: 'touchStart',
        touchPoints: [{ x, y: from }],
      });
      const steps = Math.max(2, Math.round(ms / 16));
      for (let step = 1; step <= steps; step++) {
        await touch.send('Input.dispatchTouchEvent', {
          type: 'touchMove',
          touchPoints: [{ x, y: from + ((to - from) * step) / steps }],
        });
        await page.waitForTimeout(16);
      }
      await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    };
    const { width, height } = page.viewportSize() ?? { width: 0, height: 0 };
    const sheet = page.locator('aside.detail');
    const grip = sheet.locator('.grip');
    const sheetTop = async (): Promise<number> => (await sheet.boundingBox())?.y ?? Number.NaN;
    const opensAt = height - Math.round(height / 2);

    // A link with no view: the map goes to the school, which lands on its streets in the middle
    // of the map between the search field and the sheet, as a search pick lands.
    await page.goto(`${site}?school=${PEMBROKE_HILL}`);
    await expect(sheet.locator('h2')).toHaveText('The Pembroke Hill SchoolWornall Campus');
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect(grip).toHaveAttribute('aria-expanded', 'false');
    const barBottom = await page
      .locator('.bar')
      .evaluate((bar) => bar.getBoundingClientRect().bottom);
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    await expect
      .poll(() => new URL(page.url()).searchParams.get('at'), { timeout: 30_000 })
      .not.toBeNull();
    const school = await page.evaluate(() => {
      const map = window.snowlightMap;
      if (map === undefined) throw new Error('no map');
      const point = map.project([-94.593001, 39.03606]);
      return { x: point.x, y: point.y, zoom: map.getZoom() };
    });
    expect(school.zoom).toBeCloseTo(15, 1);
    expect(Math.abs(school.x - width / 2)).toBeLessThan(4);
    expect(Math.abs(school.y - (barBottom + opensAt) / 2)).toBeLessThan(4);

    // Down by the grip: the name alone, and the most of the map in view.
    await drag(width / 2, opensAt + 12, height - 200, 400);
    await expect(sheet).toHaveAttribute('data-detent', 'peek');
    await expect.poll(sheetTop).toBeGreaterThan(height - 260);
    const peekTop = await sheetTop();
    const name = await sheet.locator('h2').boundingBox();
    expect((name?.y ?? height) + (name?.height ?? 0)).toBeLessThan(height);
    // Up by the name, most of the way: open again.
    await drag(width / 2, peekTop + 40, opensAt + 60, 400);
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    // The grip takes it up to just under the search field, and says so.
    await grip.tap();
    await expect(sheet).toHaveAttribute('data-detent', 'full');
    await expect(grip).toHaveAttribute('aria-expanded', 'true');
    await expect(grip).toHaveAttribute('aria-label', copy.detail.less);
    await expect.poll(sheetTop).toBeCloseTo(barBottom + 12, 0);
    // Dragged down by the name, even at full height: open.
    const named = await sheet.locator('h2').boundingBox();
    const nameY = (named?.y ?? 0) + 8;
    await drag(width / 2, nameY, nameY + 220, 300);
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    await expect.poll(sheetTop).toBeCloseTo(opensAt, 0);
    // Its buttons take a tap: a thumb's height, and the pin pins.
    const pin = sheet.locator('.action').first();
    expect((await pin.boundingBox())?.height).toBeGreaterThanOrEqual(44);
    await pin.tap();
    await expect(pin).toHaveAttribute('aria-pressed', 'true');
    await expect(sheet).toHaveAttribute('data-detent', 'open');
    // Pulled down past the name, it goes, and the school leaves the address.
    await drag(width / 2, opensAt + 12, height - 8, 300);
    await expect(sheet).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();

    // On the made-up storm day: the answer (today's status and the chance of a closure) is above
    // the fold as the sheet opens, and the buttons come after it.
    const stormy = await context.newPage();
    const stormProblems = watch(stormy).problems;
    await stormy.clock.setFixedTime(SYNTHETIC_NOW);
    await stormy.goto(`${site}?school=${PEMBROKE_HILL}&at=39.0334,-94.593,15`);
    const panel = stormy.locator('aside.detail');
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.delayed.today]);
    await expect(panel).toHaveAttribute('data-detent', 'open');
    await expect.poll(async () => (await panel.boundingBox())?.y).toBeCloseTo(opensAt, 0);
    const bottomOf = async (selector: string): Promise<number> => {
      const box = await panel.locator(selector).boundingBox();
      return (box?.y ?? Number.POSITIVE_INFINITY) + (box?.height ?? 0);
    };
    expect(await bottomOf('.head')).toBeLessThan(height);
    expect(await bottomOf('.status')).toBeLessThan(height);
    // A private school has no district history to give a chance: no chance card.
    await expect(panel.locator('.outlook')).toHaveCount(0);
    expect((await panel.locator('.actions').boundingBox())?.y).toBeGreaterThan(
      await bottomOf('.status'),
    );
    // Its close button: the sheet glides away, and the school leaves the address.
    await panel.locator('.close').tap();
    await expect(panel).toHaveCount(0);
    expect(new URL(stormy.url()).searchParams.get('school')).toBeNull();
    expect(problems).toEqual([]);
    expect(stormProblems).toEqual([]);
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
      // just before the menu's button at the end of that line.
      const line = await updated.boundingBox();
      const field = await page.locator('.search').boundingBox();
      const name = await page.locator('h1.wordmark').boundingBox();
      const button = await page.locator('button.menu-button').boundingBox();
      if (line === null || field === null || name === null || button === null) {
        throw new Error('no box');
      }
      if (viewport.width >= 720) {
        expect(Math.abs(line.y + line.height / 2 - (field.y + field.height / 2))).toBeLessThan(1);
        expect(Math.abs(viewport.width - 20 - (line.x + line.width))).toBeLessThan(3);
        expect(line.x).toBeGreaterThan(field.x + field.width + 100);
      } else {
        expect(Math.abs(line.y + line.height / 2 - (name.y + name.height / 2))).toBeLessThan(1);
        expect(line.y + line.height).toBeLessThanOrEqual(field.y);
        expect(line.x + line.width).toBeLessThanOrEqual(button.x - 8);
        expect(button.x - (line.x + line.width)).toBeLessThan(12);
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

  test('the update time at its longest keeps beside the field, and the list opens under it', async ({
    browser,
  }) => {
    const zone = 'America/Chicago';
    const generated = new Date('2026-01-12T12:42:00Z');
    // The next day, so the line names the file's day; offline too, it runs longest.
    const nextDay = new Date('2026-01-13T15:00:00Z');

    /**
     * The line's words right of the field and of the menu's button just after it, clear of both,
     * inside the strip, ending at its edge.
     */
    async function besideField(page: Page, width: number, where: string): Promise<void> {
      const field = await page.locator('.search').boundingBox();
      const button = await page.locator('button.menu-button').boundingBox();
      const name = await page.locator('h1.wordmark').boundingBox();
      if (field === null || button === null || name === null) throw new Error('no field');
      const words = await page.locator('.updated time').evaluate((time) => {
        const range = document.createRange();
        range.selectNodeContents(time);
        const { left, right, top, bottom } = range.getBoundingClientRect();
        return { left, right, top, bottom, clipped: time.scrollWidth > time.clientWidth };
      });
      expect(words.clipped, where).toBe(false);
      if (width < 720) {
        // A phone: between the wordmark and the menu's button on their line, over the field.
        expect(words.left, where).toBeGreaterThanOrEqual(name.x + name.width + 12);
        expect(words.right, where).toBeLessThanOrEqual(button.x - 8);
        expect(words.top, where).toBeGreaterThanOrEqual(0);
        expect(words.bottom, where).toBeLessThanOrEqual(field.y);
        return;
      }
      expect(button.x, where).toBeGreaterThanOrEqual(field.x + field.width + 8);
      expect(words.left, where).toBeGreaterThanOrEqual(button.x + button.width + 12);
      expect(Math.abs(width - 20 - words.right), where).toBeLessThan(4);
      expect(words.top, where).toBeGreaterThanOrEqual(field.y);
      expect(words.bottom, where).toBeLessThanOrEqual(field.y + field.height);
    }

    for (const viewport of [
      { width: 320, height: 568 },
      { width: 390, height: 844 },
      { width: 720, height: 900 },
      { width: 800, height: 900 },
      { width: 1024, height: 768 },
      { width: 844, height: 390 },
    ]) {
      const where = `${String(viewport.width)}x${String(viewport.height)}`;
      const context = await browser.newContext({ viewport, timezoneId: zone });
      const page = await context.newPage();
      await page.clock.setFixedTime(nextDay);
      const { problems } = watch(page);
      await page.goto(site);
      await waitForMap(page);

      // The results list runs under the field, as wide as it.
      const input = page.locator('.search-input');
      await input.click();
      await input.pressSequentially('kansas city', { delay: 20 });
      await expect(page.locator('.results [role="option"]').first()).toBeVisible();
      const field = await page.locator('.search').boundingBox();
      const list = await page.locator('.results').boundingBox();
      if (field === null || list === null) throw new Error('no box');
      expect(Math.abs(list.x - field.x), where).toBeLessThan(0.5);
      expect(Math.abs(list.width - field.width), where).toBeLessThan(0.5);
      expect(list.y, where).toBeGreaterThan(field.y + field.height);
      await input.press('Escape');
      await input.press('Escape');

      const updated = page.locator('.updated');
      await expect(updated).toHaveText(format.updatedAt(generated, zone, nextDay), {
        timeout: 30_000,
      });
      await besideField(page, viewport.width, where);
      await context.setOffline(true);
      await expect(updated).toHaveText(format.offline(generated, zone, nextDay));
      await besideField(page, viewport.width, `${where}, offline`);
      await context.setOffline(false);
      expect(problems).toEqual([]);
      await context.close();
    }
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

    // The legend counts the schools lit in each status, and dims a status with none; nothing
    // on the page moves as the counts come.
    const legend = page.locator('ul.legend');
    await expect(legend.locator('li')).toHaveText([
      `${copy.status.closed} ${format.number(1)}`,
      `${copy.status.delayed} ${format.number(1)}`,
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    await expect(legend.locator('li.is-none')).toHaveText([
      copy.status.remote,
      copy.status.earlyDismissal,
    ]);
    await expect(legend.locator('.count')).toHaveText([format.number(1), format.number(1)]);
    expect(await layoutShifts(page)).toEqual([]);
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
    // Nothing lit, nothing counted: the legend is the key alone.
    await expect(next.locator('ul.legend li')).toHaveText(
      STATUS_KEYS.map((key) => copy.status[key]),
    );
    await expect(next.locator('ul.legend .count')).toHaveCount(0);
    await expect(next.locator('ul.legend li.is-none')).toHaveCount(0);
    expect(nextWatch.problems).toEqual([]);
    await later.close();
    await context.close();
  });

  test('with the formatters’ code refused, the map, its lights, the key’s counts and search still work', async ({
    browser,
  }) => {
    // The formatters (src/copy-format.ts) load with what words with them: the menu, the panel,
    // the update time. The page's first script and the app's services need none of them.
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    await page.clock.setFixedTime(SYNTHETIC_NOW);
    const refused: string[] = [];
    await page.route(/\/assets\/copy-format-[\w-]+\.js$/, async (route) => {
      refused.push(route.request().url());
      await route.abort();
    });
    await page.goto(site);
    await waitForMap(page);
    await expect.poll(async () => (await glowStats(page)).glowCount, { timeout: 30_000 }).toBe(2);
    // The key's counts are set with the page's own formatter (copy.ts shellFormat).
    await expect(page.locator('ul.legend .count')).toHaveText([format.number(1), format.number(1)]);
    // The update time asked for the formatters, and was refused them.
    await expect.poll(() => refused.length).toBeGreaterThan(0);
    await expect(page.locator('.updated')).toHaveCount(0);

    const input = page.locator('input.search-input');
    await input.click();
    await input.pressSequentially('kansas city', { delay: 20 });
    const options = page.locator('[role="option"]');
    await expect(options).toHaveCount(2);
    await expect(options.nth(0)).toContainText('Kansas City');
    await context.close();
  });

  test('a click on two lights at the national view zooms in toward them; one alone opens as a search pick does', async ({
    browser,
  }) => {
    // Two first flights into streets, one a page (FIRST_FLIGHT_MS).
    test.setTimeout(240_000);
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      timezoneId: 'America/Chicago',
    });
    const page = await context.newPage();
    // Its calendar alone: the flights and the click's wait for a second click run in real time.
    await fixDate(page, SYNTHETIC_NOW);
    const { problems } = watch(page);
    const panel = page.locator('aside.detail');
    const input = page.locator('input.search-input');
    const cursor = (): Promise<string> =>
      page.evaluate(() => {
        const canvas = document.querySelector('.maplibregl-canvas');
        return canvas === null ? '' : getComputedStyle(canvas).cursor;
      });
    /** Where the map lands for Border Star once its panel is open, as the address and the screen say. */
    const landing = async (): Promise<number[]> => {
      const barBottom = await page
        .locator('.bar')
        .evaluate((bar) => bar.getBoundingClientRect().bottom);
      const panelRight = await panel.evaluate((aside) => aside.getBoundingClientRect().right);
      // At street level, with the school in the middle of what the panel leaves in view.
      await expect
        .poll(
          async () => {
            const view = await mapView(page);
            const school = await onScreen(page, BORDER_STAR);
            return (
              Math.abs(view.zoom - 15) < 0.01 &&
              Math.abs(school.x - (panelRight + 1440) / 2) < 2 &&
              Math.abs(school.y - (barBottom + 900) / 2) < 2
            );
          },
          { timeout: FIRST_FLIGHT_MS },
        )
        .toBe(true);
      await settleMap(page);
      const at = (new URL(page.url()).searchParams.get('at') ?? '').split(',').map(Number);
      const school = await onScreen(page, BORDER_STAR);
      return [...at, school.x, school.y];
    };

    // Picked in search, from the national view.
    await page.goto(site);
    await waitForMap(page);
    await input.click();
    await input.pressSequentially('border star', { delay: 20 });
    await page.locator('[role="option"]').first().click();
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    const picked = await landing();

    // Clicked on the national view, where the two schools' lights are under a pixel apart: a
    // click a few pixels under Border Star's could mean either, so it opens neither. The map
    // zooms in toward them instead, to where they stand apart.
    await page.goto(site);
    await waitForMap(page);
    await expect.poll(async () => (await glowStats(page)).glowCount, { timeout: 30_000 }).toBe(2);
    const national = await mapView(page);
    expect(national.zoom).toBeLessThan(5);
    const light = await onScreen(page, BORDER_STAR);
    const click = { x: Math.round(light.x), y: Math.round(light.y) + 3 };
    await page.mouse.move(click.x, click.y);
    await expect.poll(cursor).toBe('pointer');
    await page.mouse.move(click.x + 60, click.y);
    await expect.poll(cursor).toBe('grab');
    await page.mouse.click(click.x, click.y);
    await expect
      .poll(async () => (await mapView(page)).zoom, { timeout: FIRST_FLIGHT_MS })
      .toBeGreaterThan(10.9);
    await settleMap(page);
    expect((await mapView(page)).zoom).toBeLessThan(11.01);
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
    // Both tens of pixels apart now, around the middle of the part of the map a school's panel
    // leaves in view, as a pick frames its school: right of the panel, under the search strip.
    const star = await onScreen(page, BORDER_STAR);
    const hill = await onScreen(page, PEMBROKE_HILL_PLACE);
    expect(Math.hypot(star.x - hill.x, star.y - hill.y)).toBeGreaterThan(30);
    const strip = await page.locator('.bar').evaluate((bar) => bar.getBoundingClientRect().bottom);
    const open = { left: PANEL_RIGHT, top: strip, right: 1440, bottom: 900 };
    const middle = { x: (open.left + open.right) / 2, y: (open.top + open.bottom) / 2 };
    for (const place of [star, hill]) {
      expect(place.x).toBeGreaterThan(open.left);
      expect(place.y).toBeGreaterThan(open.top);
      expect(Math.hypot(place.x - middle.x, place.y - middle.y)).toBeLessThan(60);
    }

    // There, a click on Border Star's light means it: the same panel, the same address and the
    // same camera as the pick.
    await page.mouse.click(Math.round(star.x), Math.round(star.y));
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori', { timeout: 30_000 });
    await expect(panel.locator('.status .headline')).toHaveText([copy.statusLine.closed.today]);
    expect(new URL(page.url()).searchParams.get('school')).toBe('291640000557');
    await expect(input).toHaveValue('Border Star Montessori');
    await expect(panel).toBeFocused();
    // The search index keeps places to 4 decimals (search/format.ts), about 10 m, and the glow
    // the directory's own: the view in the address, and the school on the screen, as near as that.
    const clicked = await landing();
    expect(clicked).toHaveLength(5);
    clicked.forEach((value, i) => {
      expect(Math.abs(value - (picked[i] ?? Number.NaN))).toBeLessThan(i < 3 ? 2e-5 : 1);
    });

    // A click on the map where no school is leaves the panel open.
    await page.mouse.click(1300, 200);
    await page.waitForTimeout(1000);
    await expect(panel.locator('h2')).toHaveText('Border Star Montessori');
    expect(new URL(page.url()).searchParams.get('school')).toBe('291640000557');
    // The click was a step of its own: Back returns to where the zoom toward the two had come.
    await page.goBack();
    await expect(panel).toHaveCount(0);
    expect(new URL(page.url()).searchParams.get('school')).toBeNull();
    expect(Number((new URL(page.url()).searchParams.get('at') ?? '').split(',')[2])).toBeCloseTo(
      11,
      1,
    );
    expect(problems).toEqual([]);
    await context.close();
  });
});

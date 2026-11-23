/**
 * Schools at the bare address, held to the build before the mode switch (flights spec FL-2,
 * D1-D3): every map layer in its order with its visibility, and every control and word a
 * visitor can see, read from a build of the commit before the switch and kept in
 * e2e/fixtures/schools-base.json. A change to Schools' own code that hides a layer, a control
 * or a word, or adds one, shows here, where a check of this build against itself cannot see it.
 * Only the mode switch itself is left out.
 *
 * To read the fixture again from a build of the base commit served at a URL:
 *   SCHOOLS_BASE_URL=http://127.0.0.1:4590/ SCHOOLS_BASE_WRITE=1 npx playwright test e2e/schools-base.spec.ts
 */
import { readFileSync, writeFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const FIXTURE = new URL('./fixtures/schools-base.json', import.meta.url);

interface SchoolsState {
  layers: string[];
  controls: string[];
}

async function schoolsState(page: Page): Promise<SchoolsState> {
  return page.evaluate(() => {
    interface StateMap {
      getStyle(): { layers: { id: string }[] };
      getLayoutProperty(id: string, name: string): unknown;
    }
    const map = (window as unknown as { snowlightMap?: StateMap }).snowlightMap;
    const layers =
      map === undefined
        ? []
        : map.getStyle().layers.map((layer) => {
            const visibility = map.getLayoutProperty(layer.id, 'visibility');
            return `${layer.id}:${typeof visibility === 'string' ? visibility : 'visible'}`;
          });
    const seen = (element: Element): boolean => {
      if (element.closest('.mode-switch') !== null) return false;
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) return false;
      return element.checkVisibility({ opacityProperty: true, visibilityProperty: true });
    };
    const controls: string[] = [];
    const interactive = 'a, button, input, select, textarea, h1, h2, [role], [aria-label]';
    for (const element of document.body.querySelectorAll(interactive)) {
      if (!seen(element)) continue;
      const words = (text: string | null): string => (text ?? '').replace(/\s+/g, ' ').trim();
      const role = element.getAttribute('role') ?? '';
      const label = words(element.getAttribute('aria-label'));
      controls.push(
        `${element.tagName.toLowerCase()}|${role}|${label}|${words(element.textContent)}`,
      );
    }
    return { layers, controls };
  });
}

test('the bare address shows Schools as the build before the switch did: layers and controls', async ({
  page,
}, info) => {
  const base = process.env.SCHOOLS_BASE_URL;
  await page.goto(base ?? '/');
  await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
  if (base === undefined)
    await expect(page.locator('.mode-switch')).toBeVisible({ timeout: 60_000 });
  // Every late part in: the map's frames, the key's fade and the services' controls.
  await page.waitForTimeout(4000);
  const state = await schoolsState(page);
  const all = JSON.parse(readFileSync(FIXTURE, 'utf8')) as Record<string, SchoolsState>;
  if (process.env.SCHOOLS_BASE_WRITE !== undefined) {
    all[info.project.name] = state;
    writeFileSync(FIXTURE, `${JSON.stringify(all, null, 2)}\n`);
    return;
  }
  expect(state.layers.length).toBeGreaterThan(0);
  expect(state).toEqual(all[info.project.name]);
});

/** A script the page loads whose name matches, or whose body holds `marker`, aborted. */
async function abortChunk(page: Page, marker: RegExp | string): Promise<void> {
  await page.route('**/assets/*.js', async (route) => {
    const url = route.request().url();
    if (typeof marker !== 'string') {
      if (marker.test(url)) await route.abort();
      else await route.fallback();
      return;
    }
    // A chunk still in flight when the test ends meets a closed page: nothing to answer.
    try {
      const response = await route.fetch();
      const body = await response.text();
      if (body.includes(marker)) await route.abort();
      else await route.fulfill({ response, body });
    } catch {
      // The page closed.
    }
  });
}

// Every way Schools comes back in place of Flights shows the same Schools as the bare address
// of the build before the switch: no layer left hidden, no control or word missing.
for (const [name, address, kept, chunk] of [
  ['a kept Flights with no modes code', '/', true, /\/host-[\w-]+\.js$/],
  ['a Flights link with no modes code', '/?mode=flights', false, /\/host-[\w-]+\.js$/],
  ['a Flights link with no Flights code', '/?mode=flights', false, 'flights-airport-tags'],
  ['a Flights link with no app code', '/?mode=flights', false, /\/boot-[\w-]+\.js$/],
] as const) {
  test(`falls back to the build before the switch's Schools: ${name}`, async ({ page }, info) => {
    test.skip(process.env.SCHOOLS_BASE_WRITE !== undefined, 'only the bare address is read');
    if (kept)
      await page.addInitScript(() => {
        localStorage.setItem('snowlight:mode', 'flights');
      });
    await abortChunk(page, chunk);
    await page.goto(address);
    await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.mode))
      .toBe(undefined);
    // A link's address stops naming the mode the page does not show: a reload opens Schools.
    if (!kept) await expect.poll(() => new URL(page.url()).searchParams.get('mode')).toBe(null);
    await page.waitForTimeout(4000);
    const all = JSON.parse(readFileSync(FIXTURE, 'utf8')) as Record<string, SchoolsState>;
    expect(await schoolsState(page)).toEqual(all[info.project.name]);
  });
}

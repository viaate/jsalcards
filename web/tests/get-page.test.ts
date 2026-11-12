import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { copy } from '../src/copy';
import { getCopy } from '../src/copy-get';
import { waitlistCopy } from '../src/copy-waitlist';
import {
  fillPhones,
  getPageSettings,
  keepAppStore,
  markLast,
  PHONES_FILE,
  readPhones,
} from '../tools/get-page';
import { pageCopy, renderHtmlCopy } from '../tools/html-copy';
import getHtml from '../get/index.html?raw';
import indexHtml from '../index.html?raw';
import viteConfig from '../vite.config.ts?raw';

const GET = path.join(import.meta.dirname, '..', 'get');
const STORE = 'https://apps.apple.com/us/app/snowlight/id1234567890';
const MAP_LINK = 'https://snowlightmap.com/?map=1';

/** The landing as the build makes it (vite.get.config.ts), without or with the App Store link. */
function built(url: string | null): string {
  const filled = renderHtmlCopy(getHtml, pageCopy(copy, undefined, getCopy));
  return markLast(fillPhones(keepAppStore(filled, url), readPhones(GET)));
}

describe('getPageSettings', () => {
  it('has no App Store link until VITE_APP_STORE_URL names one on apps.apple.com', () => {
    expect(getPageSettings({})).toEqual({ appStoreUrl: null });
    expect(getPageSettings({ VITE_APP_STORE_URL: ' ' })).toEqual({ appStoreUrl: null });
    expect(getPageSettings({ VITE_APP_STORE_URL: STORE })).toEqual({ appStoreUrl: STORE });
    expect(() => getPageSettings({ VITE_APP_STORE_URL: 'https://example.com/app' })).toThrow(
      /not an App Store link/,
    );
  });
});

describe('the landing (get/index.html)', () => {
  it('fills every placeholder and phone from copy-get.ts and the one list', () => {
    for (const url of [null, STORE]) {
      const html = built(url);
      expect(html).not.toMatch(/%(?:copy|phone|appstore)\.[A-Za-z0-9_.]+%/u);
      expect(html).not.toContain('<!-- appstore:');
    }
    expect(built(null)).toContain(`<title>${getCopy.meta.title}</title>`);
  });

  it('shows the live map and the winter line until the App Store link is set', () => {
    const html = built(null);
    expect(html).not.toContain('appstore-badge.svg');
    expect(html).toContain(getCopy.soon);
    expect(html.match(/ data-map\s*>/gu)?.length).toBeGreaterThanOrEqual(4);
  });

  it("shows Apple's badge, linking to the App Store, once the link is set", () => {
    const html = built(STORE);
    const badges = html.match(/<a class="badge" href="([^"]+)">/gu) ?? [];
    expect(badges).toHaveLength(4);
    for (const badge of badges) expect(badge).toContain(STORE);
    expect(html).not.toContain(getCopy.soon);
    // The live map stays in sight beside the badge, at the top and in the Get section.
    expect(html.match(/ data-map\s*>/gu)?.length).toBeGreaterThanOrEqual(3);
    expect(
      /<header>[\s\S]*data-map>[\s\S]*<\/header>/u.test(html.replace(/<nav>[\s\S]*?<\/nav>/u, '')),
    ).toBe(true);
    expect(/<section id="get">[\s\S]*?data-map[\s\S]*?<\/section>/u.test(html)).toBe(true);
    // Apple's rule: the badge at least 40 px tall wherever it shows.
    for (const [, height] of html.matchAll(/appstore-badge\.svg"[^>]*height="(\d+)"/gu)) {
      expect(Number(height)).toBeGreaterThanOrEqual(40);
    }
  });

  it('links the live map with ?map=1, so the map remembers the choice', () => {
    const links = [...built(null).matchAll(/<a [^>]*href="([^"]+)"[^>]*data-map/gu)].map(
      (m) => m[1],
    );
    expect(links.length).toBeGreaterThanOrEqual(4);
    expect(new Set(links)).toEqual(new Set([MAP_LINK]));
  });

  it("takes the Add to Home Screen steps' first step to the map through ?map=1", () => {
    const steps = /<details>[\s\S]*?<\/details>/u.exec(built(null))?.[0] ?? '';
    const first = /<li>([\s\S]*?)<\/li>/u.exec(steps)?.[1] ?? '';
    expect(first).toMatch(
      new RegExp(
        `<a href="${MAP_LINK.replace(/[.?]/gu, '\\$&')}" data-map\\s*>${getCopy.get.homeSteps.open}</a`,
        'u',
      ),
    );
    // No step names the map's address for a visitor to type: that address sends an iPhone back.
    for (const step of Object.values(getCopy.get.homeSteps)) expect(step).not.toMatch(/\.com/u);
  });

  it("gives an iPhone the map's own Home Screen icon for this page", () => {
    expect(getHtml).toContain(
      '<link rel="apple-touch-icon" href="../public/icons/apple-touch-icon.v2.png" />',
    );
    expect(existsSync(path.join(GET, '..', 'public', 'icons', 'apple-touch-icon.v2.png'))).toBe(
      true,
    );
  });

  it("says the directory's count of schools, as social/facts.md has it", () => {
    const facts = readFileSync(path.join(GET, '..', '..', 'social', 'facts.md'), 'utf8');
    const count = /school directory holds ([\d,]+) US K-12 schools/u.exec(facts)?.[1];
    expect(count).toBeDefined();
    expect(getCopy.map.schools).toBe(count);
    expect(getCopy.faq.coveredAnswer).toContain(`All ${count ?? ''} `);
  });

  it('links nothing that does not exist: only its own sections and the map', () => {
    const html = built(null);
    for (const [, href] of html.matchAll(/<a [^>]*href="([^"]+)"/gu)) {
      if (href?.startsWith('#') === true) {
        expect(html, href).toContain(`id="${href.slice(1)}"`);
      } else {
        expect(href).toBe(MAP_LINK);
      }
    }
  });

  it('marks the last words of its heading', () => {
    expect(built(null)).toContain(
      '<h1 data-mark-last="3">Know about snow days <span class="mark">the night before</span>.</h1>',
    );
    expect(() => markLast('<h1 data-mark-last="5">Too short.</h1>')).toThrow(/cannot mark/);
  });

  it("carries the map's own lock, whole", () => {
    const lock = (html: string) =>
      /<div id="lock" hidden>[\s\S]*?<\/script>/u.exec(html)?.[0].replace(/^ +/gmu, '');
    expect(getHtml.match(/lock-form/gu)).toHaveLength(3);
    expect(lock(getHtml)).toBeDefined();
    expect(lock(getHtml)).toBe(lock(indexHtml));
  });

  it('runs no script but the lock', () => {
    expect(getHtml.match(/<script/gu)).toHaveLength(1);
  });
});

describe('the phone pictures (get/phones.json)', () => {
  const phones = readPhones(GET);

  it('names a picture on disk for every slot, and the page uses every slot', () => {
    const used = new Set([...getHtml.matchAll(/%phone\.([A-Za-z0-9]+)%/gu)].map((m) => m[1]));
    expect(new Set(Object.keys(phones))).toEqual(used);
    for (const phone of Object.values(phones)) {
      for (const file of [phone.file, phone.file3x]) {
        expect(existsSync(path.join(GET, 'img', file)), file).toBe(true);
      }
      expect(phone.width3x).toBeGreaterThan(phone.width);
    }
    // Every phone offers both, for two and three pixels to a point.
    const srcsets = new Set(
      [...getHtml.matchAll(/%phone\.([A-Za-z0-9]+)\.srcset%/gu)].map((m) => m[1]),
    );
    expect(srcsets).toEqual(used);
    expect(PHONES_FILE).toBe('phones.json');
    expect(JSON.parse(readFileSync(path.join(GET, PHONES_FILE), 'utf8'))).toEqual(phones);
  });

  it('refuses a slot the list does not have, or a file that is no picture', () => {
    expect(() => fillPhones('%phone.nope%', phones)).toThrow(/no phone picture/);
    expect(() =>
      fillPhones('%phone.hero%', {
        hero: { from: 'x', file: '../x.html', width: 1, file3x: 'x.webp', width3x: 2 },
      }),
    ).toThrow(/names no picture/);
    expect(() =>
      fillPhones('%phone.hero.srcset%', {
        hero: { from: 'x', file: 'x.webp', width: 1, file3x: 'x"y.webp', width3x: 2 },
      }),
    ).toThrow(/names no picture/);
    expect(fillPhones('%phone.hero%', phones)).toBe(`./img/${phones.hero?.file ?? ''}`);
    expect(fillPhones('%phone.hero.srcset%', phones)).toBe(
      `./img/${phones.hero?.file ?? ''} 2x, ./img/${phones.hero?.file3x ?? ''} 3x`,
    );
  });
});

describe("the map's own build", () => {
  it('never builds or links the landing', () => {
    expect(viteConfig).not.toMatch(/get\/|getPage|copy-get/u);
    expect(indexHtml).not.toMatch(/href="[^"]*getsnowlight/u);
  });

  it('keeps the landing words apart from copy.ts and the waitlist', () => {
    expect(Object.hasOwn(copy, 'get')).toBe(false);
    expect(() => pageCopy({ get: 'x' }, undefined, getCopy)).toThrow(/own "get"/);
    const both = pageCopy(copy, waitlistCopy, getCopy);
    expect(renderHtmlCopy('%copy.get.openMap% %copy.waitlist.when%', both)).toBe(
      `${getCopy.openMap} ${waitlistCopy.when}`,
    );
  });
});

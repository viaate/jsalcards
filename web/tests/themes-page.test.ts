/**
 * index.html's first script with the themes the build writes in
 * (tools/themes.ts): it puts on only this build's version of the theme a
 * device keeps, and never one this build may not show, before anything paints.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import indexHtml from '../index.html?raw';
import { MIDNIGHT_BAR } from '../src/theme/engine';
import { THEME_RETRY, THEME_STORAGE_KEY } from '../src/theme/event';
import { PAGE_THEMES_ID } from '../src/theme/page';
import { THEMES } from '../src/theme/themes';
import { PAGE_THEMES_BLOCK, pageThemes, pageThemesJson, shownThemes } from '../tools/themes';

const FONTS = { latin: '/assets/latin-1.woff2', latinExt: '/assets/latin-ext-1.woff2' };

/** index.html's first script: the one right after the themes' block. */
function firstScript(): string {
  const block = PAGE_THEMES_BLOCK.exec(indexHtml);
  if (block === null) throw new Error('index.html has no themes block');
  const rest = indexHtml.slice(block.index + block[0].length);
  const match = /^\s*<script>([\s\S]*?)<\/script>/.exec(rest);
  if (match?.[1] === undefined) throw new Error('no first script right after the themes block');
  return match[1];
}

/**
 * Loads a page from a build that may show `preview`, with `kept` on the
 * device, and the sheet themes' style sheets at `sheets`.
 */
function load(kept: unknown, preview?: string, sheets: Record<string, string> = {}): void {
  document.head.innerHTML = '<meta name="theme-color" content="#000000">';
  const block = document.createElement('script');
  block.type = 'application/json';
  block.id = PAGE_THEMES_ID;
  block.textContent = pageThemesJson(pageThemes(shownThemes(preview), FONTS, sheets));
  document.head.append(block);
  if (kept === null) localStorage.removeItem(THEME_STORAGE_KEY);
  else localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(kept));
  run();
}

/** Runs the first script as the page does: a script element in the head. */
function run(): void {
  const script = document.createElement('script');
  script.textContent = firstScript();
  document.head.append(script);
}

function bg(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute(THEME_RETRY);
  document.head.innerHTML = '';
});

describe("index.html's first script", () => {
  it('has the block the build fills, once, right before it', () => {
    expect(indexHtml.match(new RegExp(PAGE_THEMES_BLOCK, 'g'))).toHaveLength(1);
    expect(firstScript()).toContain(`'${THEME_STORAGE_KEY}'`);
    expect(firstScript()).toContain(`'${PAGE_THEMES_ID}'`);
  });

  it('puts on the kept theme as this build writes it, whatever the device kept with it', () => {
    load({ id: 'daylight', css: ':root{--bg:#ff00ff}', color: '#ff00ff' });
    expect(document.documentElement.dataset.theme).toBe('daylight');
    expect(bg()).toBe(THEMES.daylight.tokens.bg);
    expect(document.documentElement.outerHTML).not.toContain('ff00ff');
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe(
      THEMES.daylight.tokens.bg,
    );
  });

  it('never puts on a theme this build does not carry, and leaves it kept for one that does', () => {
    // A theme a newer build adds.
    for (const id of ['a-theme-from-a-newer-build']) {
      load({ id });
      expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
      expect(document.getElementById('sl-theme')).toBeNull();
      expect(document.querySelector('link[rel="preload"]')).toBeNull();
      expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(JSON.stringify({ id }));
    }
  });

  it('leaves Midnight, and anything that is not a kept theme, as the page draws it', () => {
    for (const kept of [null, { id: 7 }, 'daylight']) {
      load(kept);
      expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    }
    localStorage.setItem(THEME_STORAGE_KEY, '{broken');
    expect(run).not.toThrow();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('puts on a kept Snowball and fetches its face first', () => {
    load({ id: 'snowball' });
    expect(document.documentElement.dataset.theme).toBe('snowball');
    const face = document.querySelector<HTMLLinkElement>('link[rel="preload"]');
    expect(face?.getAttribute('href')).toBe(FONTS.latin);
    expect(face?.as).toBe('font');
  });

  it('writes in a kept theme’s own style sheet where it stands, so the page waits for it', () => {
    const written: string[] = [];
    vi.spyOn(document, 'write').mockImplementation((...html: string[]) => {
      written.push(html.join(''));
    });
    load({ id: 'snowball' }, undefined, { snowball: '/assets/themes/snowball-1.css' });
    expect(written).toHaveLength(1);
    expect(written).toEqual([
      '<link rel="stylesheet" id="sl-theme" href="/assets/themes/snowball-1.css">',
    ]);
    expect(document.documentElement.dataset.theme).toBe('snowball');
    expect(document.querySelector('style#sl-theme')).toBeNull();
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe(
      THEMES.snowball.tokens.bg,
    );
    expect(document.querySelector('link[rel="preload"]')?.getAttribute('href')).toBe(FONTS.latin);
    // Where the sheet cannot load, the page is Midnight's, the browser's bar too, and marked for
    // the engine to try the sheet again (src/app/boot.ts).
    expect(document.documentElement.hasAttribute(THEME_RETRY)).toBe(false);
    document.head.insertAdjacentHTML('beforeend', written[0] ?? '');
    document.getElementById('sl-theme')?.dispatchEvent(new Event('error'));
    expect(document.getElementById('sl-theme')).toBeNull();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute('content')).toBe(
      MIDNIGHT_BAR,
    );
    expect(document.documentElement.hasAttribute(THEME_RETRY)).toBe(true);
    // Every other theme the page carries whole: nothing written in.
    load({ id: 'aurora' }, undefined, { snowball: '/assets/themes/snowball-1.css' });
    expect(written).toHaveLength(1);
    expect(document.querySelector('style#sl-theme')).not.toBeNull();
  });

  it('carries every released theme, in the shop’s order', () => {
    const json = pageThemesJson(pageThemes(shownThemes(''), FONTS));
    expect(Object.keys(JSON.parse(json) as object)).toEqual([
      'daylight',
      'aurora',
      'ember',
      'glacier',
      'dusk',
      'snowball',
      'bronze',
      'silver',
      'gold',
    ]);
    // Safe inside a <script>, whatever a theme's CSS holds.
    expect(pageThemesJson({ daylight: { rules: ['</script>'], color: '#fff' } })).not.toContain(
      '</',
    );
  });
});

/**
 * The approval gate, kept for themes to come (unreleased.ts): none waits at
 * present, so these run with a stand-in, next-frost, listed as waiting. A build
 * that names no unreleased theme carries none of it, lists none, never puts
 * one on, and shows Midnight where a device kept one; a build that names it
 * (VITE_THEMES_PREVIEW) shows it, last in the list.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import indexHtml from '../../../index.html?raw';
import {
  carriesUnreleased,
  pageThemes,
  pageThemesJson,
  shownThemes,
  themes,
} from '../../../tools/themes';
import { createThemeEngine, themeAvailable } from '../engine';
import { listedThemes } from '../shop';
import { THEME_STORAGE_KEY } from '../event';
import { THEME_IDS, THEMES_UNRELEASED, isThemeId, themeOf, type ThemeId } from '../themes';

const { FROST } = vi.hoisted(() => ({
  /** The stand-in: a dark theme waiting for the owner's yes. */
  FROST: {
    id: 'next-frost',
    scheme: 'dark',
    access: 'shop',
    tokens: {
      bg: '#06121c',
      surface1: '#0d2030',
      surface2: '#13293b',
      border1: '#1f3a52',
      border2: '#2a4a66',
      text1: '#eef7ff',
      text2: '#b5c9db',
      text3: '#8ca3b8',
      accent: '#bfe6ff',
      closed: '#7fd4ff',
      delayed: '#ffc46b',
      remote: '#b79cff',
      early: '#6bffb0',
      onClosed: '#000',
      open: '#9fb4c8',
      chance: '#eef7ff',
      mapLabelDim: '#8ca3b8',
      land: '#06121c',
      ground: '#06121c',
      water: '#0a1826',
      park: '#0b1a24',
      grounds: '#0e1d2a',
      groundsEdge: '#2a4a66',
      shore: '#2f526f',
      minorRoad: '#132636',
      majorRoad: '#4d7391',
      lineOutline: '#2f526f',
      lineState: '#1f3a52',
      lineOutlinePhone: '#3b6283',
      lineStatePhone: '#2a4a66',
      dot: '#dcebfb',
      dotRing: '#06121c',
      veil: '6 18 28',
      shadow: '0 0 0',
      sheen: '255 255 255',
      halo: '#06121c',
      amb: 'none',
    },
    glow: { mode: 'glow', outline: '#000000', outlineWidth: 0, burst: false },
    lineWidths: null,
    roadScale: 1,
  },
}));

vi.mock('../unreleased', () => ({
  UNRELEASED_IDS: ['next-frost'],
  UNRELEASED_THEMES: { 'next-frost': FROST },
}));

/** The stand-in's id. */
const FROST_ID: ThemeId = 'next-frost';
const FONTS = { latin: '/assets/latin.woff2', latinExt: '/assets/latin-ext.woff2' };

function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => {
      items.clear();
    },
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => {
      items.delete(key);
    },
    setItem: (key, value) => {
      items.set(key, value);
    },
  };
}

afterEach(() => {
  vi.unstubAllEnvs();
  document.documentElement.removeAttribute('data-theme');
  document.getElementById('sl-theme')?.remove();
});

describe('a theme waiting for approval (a stand-in)', () => {
  it('is carried by the tools and the tests, last, and known as waiting', () => {
    expect(THEME_IDS.at(-1)).toBe(FROST_ID);
    expect(THEMES_UNRELEASED).toEqual(new Set([FROST_ID]));
    expect(isThemeId(FROST_ID)).toBe(true);
    expect(themeOf(FROST_ID).tokens.bg).toBe(FROST.tokens.bg);
  });

  it('stays out of a default build: its scripts, its page and its list', () => {
    // vite.config.ts leaves it out of the scripts as code never run.
    expect(carriesUnreleased(undefined)).toBe(false);
    expect(carriesUnreleased('')).toBe(false);
    expect(shownThemes(undefined)).not.toContain(FROST_ID);
    expect(shownThemes(undefined)).toContain('snowball');
    const page = pageThemes(shownThemes(undefined), FONTS);
    expect(pageThemesJson(page)).not.toMatch(/frost/i);
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    expect(themeAvailable(FROST_ID)).toBe(false);
    expect(listedThemes().map((theme) => theme.id)).not.toContain(FROST_ID);
  });

  it('is not in the page a default build writes, and is in a preview build’s', () => {
    const written = (preview: string | undefined): string => {
      const plugin = themes(preview);
      const resolved = plugin.configResolved as unknown as (config: object) => void;
      resolved({ base: '/', command: 'build' });
      const html = plugin.transformIndexHtml as unknown as {
        handler: (html: string) => string;
      };
      return html.handler(indexHtml);
    };
    expect(written(undefined)).not.toMatch(/frost/i);
    expect(written(undefined)).toMatch(/"snowball":\{"sheet":"\/assets\/themes\/snowball-/);
    expect(written('next-frost')).toMatch(/"next-frost":\{"rules":/);
  });

  it('is never put on by a default build, and a device that kept it sees Midnight', async () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    const storage = memoryStorage();
    const page = pageThemes(shownThemes(undefined), FONTS);
    const engine = createThemeEngine({ themes: page, storage, win: null });
    await expect(engine.useTheme(FROST_ID)).resolves.toBe(false);
    await expect(engine.previewTheme(FROST_ID)).resolves.toBe(false);
    expect(engine.current).toBe('midnight');
    // Even a page that carried it is refused by a build that may not show it.
    const preview = pageThemes(shownThemes('next-frost'), FONTS);
    await expect(
      createThemeEngine({ themes: preview, storage, win: null }).useTheme(FROST_ID),
    ).resolves.toBe(false);
    // Kept from a preview build: Midnight, and the id stays kept.
    const kept = JSON.stringify({ id: 'next-frost' });
    storage.setItem(THEME_STORAGE_KEY, kept);
    document.documentElement.setAttribute('data-theme', 'next-frost');
    const next = createThemeEngine({ themes: page, storage, win: null });
    expect(next.current).toBe('midnight');
    expect(next.kept).toBe('midnight');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe(kept);
  });

  it('is shown by a build that names it, last in the list', async () => {
    expect(carriesUnreleased('next-frost')).toBe(true);
    expect(carriesUnreleased(' snowball , next-frost ')).toBe(true);
    expect(shownThemes('next-frost').at(-1)).toBe(FROST_ID);
    vi.stubEnv('VITE_THEMES_PREVIEW', 'next-frost');
    expect(themeAvailable(FROST_ID)).toBe(true);
    expect(listedThemes().map((theme) => theme.id)).toEqual(THEME_IDS);
    const page = pageThemes(shownThemes('next-frost'), FONTS);
    const engine = createThemeEngine({ themes: page, storage: memoryStorage(), win: null });
    await expect(engine.useTheme(FROST_ID)).resolves.toBe(true);
    expect(document.documentElement.dataset.theme).toBe('next-frost');
  });
});

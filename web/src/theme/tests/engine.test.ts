import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { pageThemes, shownThemes } from '../../../tools/themes';
import { createThemeEngine, listedThemes, themeAvailable, THEME_STYLE_ID } from '../engine';
import type { EngineOptions } from '../engine';
import { themeCss, themeProperties } from '../css';
import { THEME_EVENT, THEME_STORAGE_KEY } from '../event';
import { PAGE_THEMES_ID, readPageThemes } from '../page';
import { snowballRules } from '../snowball';
import { THEMES, THEME_IDS, themeOf } from '../themes';
import type { ThemeId } from '../themes';

const FONTS = { latin: '/assets/latin.woff2', latinExt: '/assets/latin-ext.woff2' };
/** The themes a default build's page carries, and a Snowball preview build's. */
const PAGE = pageThemes(shownThemes(undefined), FONTS);
const PREVIEW_PAGE = pageThemes(shownThemes('snowball'), FONTS);

/** A theme's rules as the page carries them. */
function rulesOf(id: ThemeId): readonly string[] {
  return PREVIEW_PAGE[id]?.rules ?? [];
}

/** An engine on the default build's page, hearing no other tab unless given one. */
function engineOn(options: EngineOptions = {}): ReturnType<typeof createThemeEngine> {
  return createThemeEngine({ themes: PAGE, win: null, ...options });
}

/** Another tab's window: what it hears, to say to it. */
function otherTabs(): {
  win: Pick<Window, 'addEventListener'>;
  say(key: string | null, value: string | null): void;
} {
  const heard: ((event: StorageEvent) => void)[] = [];
  return {
    win: {
      addEventListener: (type: string, listener: unknown) => {
        if (type === 'storage') heard.push(listener as (event: StorageEvent) => void);
      },
    } as Pick<Window, 'addEventListener'>,
    say(key, value) {
      for (const listener of heard) listener(new StorageEvent('storage', { key, newValue: value }));
    },
  };
}

function bar(): string | null {
  return document.querySelector('meta[name="theme-color"]')?.getAttribute('content') ?? null;
}

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

/** How many rules the page's theme sheet holds. */
function sheetRules(): number {
  const style = document.getElementById(THEME_STYLE_ID) as HTMLStyleElement | null;
  return style?.sheet?.cssRules.length ?? 0;
}

function reset(): void {
  document.getElementById(THEME_STYLE_ID)?.remove();
  document.documentElement.removeAttribute('data-theme');
  document.head.innerHTML =
    '<meta name="theme-color" content="#000000"><meta name="color-scheme" content="dark">';
}

beforeEach(reset);
afterEach(() => {
  vi.unstubAllEnvs();
  reset();
});

describe('the theme engine', () => {
  it('leaves Midnight as the page draws it: no style, no attribute, nothing kept', () => {
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    expect(engine.current).toBe('midnight');
    expect(document.getElementById(THEME_STYLE_ID)).toBeNull();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(PAGE.midnight).toBeUndefined();
  });

  it('puts a theme on at once, keeps its id, colors the bar and tells the map', () => {
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    const heard: unknown[] = [];
    const listener = (event: Event): void => {
      heard.push((event as CustomEvent).detail);
    };
    document.addEventListener(THEME_EVENT, listener);
    expect(engine.useTheme('daylight')).toBe(true);
    document.removeEventListener(THEME_EVENT, listener);
    expect(document.documentElement.getAttribute('data-theme')).toBe('daylight');
    expect(sheetRules()).toBe(rulesOf('daylight').length);
    expect(bar()).toBe(THEMES.daylight.tokens.bg);
    expect(getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()).toBe(
      THEMES.daylight.tokens.bg,
    );
    expect(heard).toEqual([{ id: 'daylight', preview: false }]);
    const kept = JSON.parse(storage.getItem(THEME_STORAGE_KEY) ?? 'null') as Record<string, string>;
    expect(kept).toEqual({ id: 'daylight' });
    engine.useTheme('ember');
    expect(bar()).toBe(THEMES.ember.tokens.bg);
    // Back to Midnight: the page's own CSS and bar, and nothing kept.
    engine.useTheme(null);
    expect(bar()).toBe('#000000');
    expect(document.getElementById(THEME_STYLE_ID)).toBeNull();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('tries a theme without keeping it, and goes back to the kept one', () => {
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    engine.useTheme('glacier');
    const changes: unknown[] = [];
    engine.onChange((change) => changes.push(change));
    expect(engine.previewTheme('aurora')).toBe(true);
    expect(engine.current).toBe('aurora');
    expect(engine.kept).toBe('glacier');
    expect(JSON.parse(storage.getItem(THEME_STORAGE_KEY) ?? '{}')).toMatchObject({ id: 'glacier' });
    engine.endPreview();
    expect(engine.current).toBe('glacier');
    expect(document.documentElement.getAttribute('data-theme')).toBe('glacier');
    expect(changes).toEqual([
      { id: 'aurora', preview: true },
      { id: 'glacier', preview: false },
    ]);
  });

  it('takes over what index.html put on as it is: no second sheet, no restyle', () => {
    const storage = memoryStorage();
    // An older build kept the theme's CSS too: only the id counts.
    storage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({ id: 'ember', css: ':root{--bg:#ff00ff}', color: '#000' }),
    );
    // index.html's first script, as it runs before the page's: the same page's rules.
    const style = document.createElement('style');
    style.id = THEME_STYLE_ID;
    style.textContent = rulesOf('ember').join('');
    document.head.append(style);
    document.documentElement.setAttribute('data-theme', 'ember');
    const heard: unknown[] = [];
    const listener = (event: Event): void => {
      heard.push((event as CustomEvent).detail);
    };
    document.addEventListener(THEME_EVENT, listener);
    const engine = engineOn({ storage });
    document.removeEventListener(THEME_EVENT, listener);
    expect(engine.current).toBe('ember');
    expect(engine.kept).toBe('ember');
    expect(document.getElementById(THEME_STYLE_ID)).toBe(style);
    expect(heard).toEqual([]);
    expect(getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()).toBe(
      THEMES.ember.tokens.bg,
    );
    // The old value stands as it was: the engine writes nothing at its start.
    expect(JSON.parse(storage.getItem(THEME_STORAGE_KEY) ?? 'null')).toMatchObject({
      css: ':root{--bg:#ff00ff}',
    });
    // And the next change replaces the sheet as any other.
    engine.useTheme('dusk');
    expect(document.getElementById(THEME_STYLE_ID)).not.toBe(style);
    expect(sheetRules()).toBe(rulesOf('dusk').length);
  });

  it('puts the kept theme on where index.html did not, and tells the map', () => {
    const storage = memoryStorage();
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ id: 'aurora' }));
    const heard: unknown[] = [];
    const listener = (event: Event): void => {
      heard.push((event as CustomEvent).detail);
    };
    document.addEventListener(THEME_EVENT, listener);
    const engine = engineOn({ storage });
    document.removeEventListener(THEME_EVENT, listener);
    expect(engine.current).toBe('aurora');
    expect(document.documentElement.getAttribute('data-theme')).toBe('aurora');
    expect(sheetRules()).toBe(rulesOf('aurora').length);
    expect(heard).toEqual([{ id: 'aurora', preview: false }]);
  });

  it('shows Midnight for a kept theme this build does not carry, and leaves it kept', () => {
    // A newer build's tab kept a theme this older page does not carry (or a theme the game added).
    for (const raw of [
      JSON.stringify({ id: 'aurora' }),
      JSON.stringify({ id: 'a-theme-from-a-newer-build' }),
    ]) {
      reset();
      const storage = memoryStorage();
      storage.setItem(THEME_STORAGE_KEY, raw);
      const daylight = PAGE.daylight;
      if (daylight === undefined) throw new Error('no Daylight');
      const tabs = otherTabs();
      const engine = engineOn({ storage, themes: { daylight }, win: tabs.win });
      expect(engine.current).toBe('midnight');
      expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
      expect(storage.getItem(THEME_STORAGE_KEY)).toBe(raw);
      // A try and its end write nothing either.
      engine.previewTheme('daylight');
      engine.endPreview();
      expect(engine.current).toBe('midnight');
      // Nor does hearing the other tab keep it again.
      tabs.say(THEME_STORAGE_KEY, raw);
      expect(engine.current).toBe('midnight');
      expect(storage.getItem(THEME_STORAGE_KEY)).toBe(raw);
    }
  });

  it('reads the themes the page carries, and nothing that is not one', () => {
    const block = document.createElement('script');
    block.type = 'application/json';
    block.id = PAGE_THEMES_ID;
    block.textContent = JSON.stringify({ ...PAGE, neon: 7, aurora: { rules: [1], color: '' } });
    document.head.append(block);
    const read = readPageThemes(document);
    expect(Object.keys(read).sort()).toEqual(
      Object.keys(PAGE)
        .filter((id) => id !== 'aurora')
        .sort(),
    );
    block.textContent = '{broken';
    expect(readPageThemes(document)).toEqual({});
    block.remove();
    expect(readPageThemes(document)).toEqual({});
  });

  it('refuses a theme the page does not carry', () => {
    const daylight = PAGE.daylight;
    if (daylight === undefined) throw new Error('no Daylight');
    const engine = engineOn({ storage: memoryStorage(), themes: { daylight } });
    expect(engine.useTheme('aurora')).toBe(false);
    expect(engine.useTheme('daylight')).toBe(true);
  });

  it('follows another tab’s change, after a try', () => {
    const storage = memoryStorage();
    const tabs = otherTabs();
    const engine = engineOn({ storage, win: tabs.win });
    engine.useTheme('daylight');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'gold' }));
    expect(engine.current).toBe('gold');
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    // During a try the page keeps the tried theme, and goes back to the other tab's after it.
    engine.previewTheme('dusk');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'silver' }));
    expect(engine.current).toBe('dusk');
    engine.endPreview();
    expect(engine.current).toBe('silver');
    // Gone there, gone here; and a theme this build may not show is Midnight.
    tabs.say(THEME_STORAGE_KEY, null);
    expect(engine.current).toBe('midnight');
    engine.useTheme('aurora');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'snowball' }));
    expect(engine.current).toBe('midnight');
    tabs.say('another key', JSON.stringify({ id: 'gold' }));
    expect(engine.current).toBe('midnight');
  });

  it('ignores a kept value that is not a theme', () => {
    const storage = memoryStorage();
    storage.setItem(THEME_STORAGE_KEY, '{not json');
    expect(engineOn({ storage }).current).toBe('midnight');
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ id: 'neon', css: '' }));
    expect(engineOn({ storage }).current).toBe('midnight');
  });

  it('works where the device keeps nothing', () => {
    const throwing = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    } as unknown as Storage;
    const engine = engineOn({ storage: throwing });
    expect(engine.useTheme('dusk')).toBe(true);
    expect(engine.current).toBe('dusk');
  });
});

describe('the approval gate', () => {
  it('never offers or puts on Snowball until a build names it', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    expect(themeAvailable('snowball')).toBe(false);
    expect(listedThemes().map((theme) => theme.id)).not.toContain('snowball');
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    expect(engine.useTheme('snowball')).toBe(false);
    expect(engine.previewTheme('snowball')).toBe(false);
    expect(engine.current).toBe('midnight');
    // The default build's page carries none of it: not its CSS, not its face.
    expect(PAGE.snowball).toBeUndefined();
    expect(JSON.stringify(PAGE)).not.toMatch(/snowball|Fredoka|woff2/i);
    // Even a page that did is refused by a build that may not show it.
    expect(engineOn({ storage, themes: PREVIEW_PAGE }).useTheme('snowball')).toBe(false);
    // A device that kept it from a preview build sees Midnight, and keeps the id.
    const kept = JSON.stringify({ id: 'snowball', css: '', color: '' });
    storage.setItem(THEME_STORAGE_KEY, kept);
    document.documentElement.setAttribute('data-theme', 'snowball');
    const next = engineOn({ storage });
    expect(next.current).toBe('midnight');
    expect(next.kept).toBe('midnight');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe(kept);
  });

  it('lets a preview build show it, last in the list', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', 'snowball');
    expect(themeAvailable('snowball')).toBe(true);
    expect(listedThemes().map((theme) => theme.id)).toEqual(THEME_IDS);
    const engine = engineOn({ storage: memoryStorage(), themes: PREVIEW_PAGE });
    expect(engine.useTheme('snowball')).toBe(true);
    // Its face, fetched first where it is kept (index.html).
    expect(PREVIEW_PAGE.snowball?.font).toBe(FONTS.latin);
  });

  it('lists every released theme in the shop’s order', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    expect(listedThemes().map((theme) => theme.id)).toEqual([
      'midnight',
      'daylight',
      'aurora',
      'ember',
      'glacier',
      'dusk',
      'bronze',
      'silver',
      'gold',
    ]);
  });
});

describe('a theme as CSS', () => {
  it.each(THEME_IDS.filter((id) => id !== 'midnight'))(
    'scopes %s to its root and sets every token the page and the map read',
    (id) => {
      const css = themeCss(themeOf(id));
      expect(css.startsWith(`:root[data-theme='${id}']{`)).toBe(true);
      const names = themeProperties(themeOf(id)).map(([name]) => name);
      for (const name of [
        '--bg',
        '--surface-1',
        '--text-1',
        '--status-closed',
        '--status-open',
        '--land',
        '--line-outline',
        '--line-state',
        '--map-roads',
        '--glow-mode',
        '--veil',
        '--halo',
      ]) {
        expect(names).toContain(name);
      }
      // A phone's clearer lines, as index.html has them.
      expect(css).toContain('@media (max-width: 719px), (max-height: 519px)');
      // Colors only: no theme changes a box's size, but Snowball's outlines.
      if (id !== 'snowball')
        expect(css).not.toMatch(/[;{](?:width|height|padding|margin|font-size):/);
    },
  );

  it('gives Snowball its ink outlines, drop offsets and its own face, scoped to it', () => {
    const css = themeCss(themeOf('snowball'), snowballRules(FONTS));
    expect(css).toContain(`url("${FONTS.latin}")`);
    expect(css).toContain("font-family:'Fredoka Variable'");
    expect(css).toMatch(/border-width:2\.5px/);
    expect(css).toMatch(/box-shadow:4px 4px 0 0 var\(--border-2\)/);
    for (const rule of css.split('}').filter((part) => part.includes('{'))) {
      const body = rule.replace(/^@media[^{]*\{/, '');
      const selector = body.slice(0, body.indexOf('{'));
      if (selector.startsWith('@font-face') || selector === '') continue;
      for (const part of selector.split(','))
        expect(part.trim()).toMatch(/^:root\[data-theme='snowball'\]/);
    }
  });
});

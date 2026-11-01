import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { pageThemes, shownThemes } from '../../../tools/themes';
import {
  createThemeEngine,
  MIDNIGHT_BAR,
  SPARE_SHEET,
  themeAvailable,
  THEME_STYLE_ID,
} from '../engine';
import { listedThemes } from '../shop';
import type { EngineOptions, SheetLoader } from '../engine';
import { themeCss, themeProperties } from '../css';
import { THEME_EVENT, THEME_RETRY, THEME_STORAGE_KEY } from '../event';
import { PAGE_THEMES_ID, readPageThemes } from '../page';
import { snowballRules } from '../snowball';
import { THEMES, THEME_IDS, themeOf } from '../themes';
import type { ThemeId } from '../themes';

const FONTS = { latin: '/assets/latin.woff2', latinExt: '/assets/latin-ext.woff2' };
/** The themes a default build's page carries. */
const PAGE = pageThemes(shownThemes(undefined), FONTS);

/** A theme's rules as the page carries them. */
function rulesOf(id: ThemeId): readonly string[] {
  return PAGE[id]?.rules ?? [];
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

  it('puts a theme on at once, keeps its id, colors the bar and tells the map', async () => {
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    const heard: unknown[] = [];
    const listener = (event: Event): void => {
      heard.push((event as CustomEvent).detail);
    };
    document.addEventListener(THEME_EVENT, listener);
    await expect(engine.useTheme('daylight')).resolves.toBe(true);
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
    void engine.useTheme('ember');
    expect(bar()).toBe(THEMES.ember.tokens.bg);
    // Back to Midnight: the page's own CSS and bar, and nothing kept.
    void engine.useTheme(null);
    expect(bar()).toBe('#000000');
    expect(document.getElementById(THEME_STYLE_ID)).toBeNull();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('tries a theme without keeping it, and goes back to the kept one', async () => {
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    void engine.useTheme('glacier');
    const changes: unknown[] = [];
    engine.onChange((change) => changes.push(change));
    await expect(engine.previewTheme('aurora')).resolves.toBe(true);
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
    void engine.useTheme('dusk');
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
      void engine.previewTheme('daylight');
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

  it('refuses a theme the page does not carry', async () => {
    const daylight = PAGE.daylight;
    if (daylight === undefined) throw new Error('no Daylight');
    const engine = engineOn({ storage: memoryStorage(), themes: { daylight } });
    await expect(engine.useTheme('aurora')).resolves.toBe(false);
    await expect(engine.useTheme('daylight')).resolves.toBe(true);
  });

  it('follows another tab’s change, after a try', () => {
    const storage = memoryStorage();
    const tabs = otherTabs();
    const engine = engineOn({ storage, win: tabs.win });
    void engine.useTheme('daylight');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'gold' }));
    expect(engine.current).toBe('gold');
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    // During a try the page keeps the tried theme, and goes back to the other tab's after it.
    void engine.previewTheme('dusk');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'silver' }));
    expect(engine.current).toBe('dusk');
    engine.endPreview();
    expect(engine.current).toBe('silver');
    // Gone there, gone here; and a theme this build may not show is Midnight.
    tabs.say(THEME_STORAGE_KEY, null);
    expect(engine.current).toBe('midnight');
    void engine.useTheme('aurora');
    tabs.say(THEME_STORAGE_KEY, JSON.stringify({ id: 'neon' }));
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

  it('works where the device keeps nothing', async () => {
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
    await expect(engine.useTheme('dusk')).resolves.toBe(true);
    expect(engine.current).toBe('dusk');
  });
});

describe('the shop’s list', () => {
  it('lists every released theme in the shop’s order, Snowball after Dusk', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    expect(listedThemes().map((theme) => theme.id)).toEqual([
      'midnight',
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
    expect(themeOf('snowball').access).toBe('shop');
  });

  it('offers Snowball in a default build, and puts it on, tried or kept', async () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    expect(themeAvailable('snowball')).toBe(true);
    expect(PAGE.snowball?.font).toBe(FONTS.latin);
    const storage = memoryStorage();
    const engine = engineOn({ storage });
    await expect(engine.previewTheme('snowball')).resolves.toBe(true);
    expect(engine.current).toBe('snowball');
    engine.endPreview();
    expect(engine.current).toBe('midnight');
    await expect(engine.useTheme('snowball')).resolves.toBe(true);
    expect(engine.current).toBe('snowball');
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe(JSON.stringify({ id: 'snowball' }));
  });

  it('shows Snowball to a device that kept it, from a preview build or this one', () => {
    vi.stubEnv('VITE_THEMES_PREVIEW', '');
    const storage = memoryStorage();
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ id: 'snowball', css: '', color: '' }));
    const engine = engineOn({ storage });
    expect(engine.kept).toBe('snowball');
    expect(engine.current).toBe('snowball');
    expect(document.documentElement.dataset.theme).toBe('snowball');
  });
});

describe('a theme with a style sheet of its own', () => {
  const SHEET = '/assets/themes/snowball-1.css';
  /** A default build's page as the build writes it: Snowball as its sheet's address. */
  const SHEET_PAGE = pageThemes(shownThemes(undefined), FONTS, { snowball: SHEET });

  /** The addresses of the theme sheets the page keeps loaded and unused. */
  function spares(): (string | null)[] {
    return [...document.querySelectorAll(`link[${SPARE_SHEET}]`)].map((link) =>
      link.getAttribute('href'),
    );
  }

  /** A loader whose loads finish when the test says, each with its sheet or none. */
  function loader(): {
    load: SheetLoader;
    asked: { href: string; family: string | undefined }[];
    finish(ok: boolean): Promise<void>;
  } {
    const waiting: ((ok: boolean) => void)[] = [];
    const asked: { href: string; family: string | undefined }[] = [];
    return {
      asked,
      load: (doc, href, family) => {
        asked.push({ href, family });
        const link = doc.createElement('link');
        link.rel = 'stylesheet';
        link.setAttribute('href', href);
        doc.head.append(link);
        return new Promise((resolve) => {
          waiting.push((ok) => {
            if (!ok) link.remove();
            resolve(ok ? link : null);
          });
        });
      },
      async finish(ok) {
        waiting.shift()?.(ok);
        await Promise.resolve();
        await Promise.resolve();
      },
    };
  }

  it('carries only the sheet’s address, its bar color and its face', () => {
    expect(SHEET_PAGE.snowball).toEqual({
      sheet: SHEET,
      color: themeOf('snowball').tokens.bg,
      font: FONTS.latin,
      family: 'Fredoka Variable',
    });
    expect(JSON.stringify(SHEET_PAGE)).not.toMatch(/data-theme='snowball'|@font-face/);
  });

  it('goes on once its sheet and face have loaded, in one change, and off at once', async () => {
    const sheets = loader();
    const events: string[] = [];
    const heard = (event: Event): void => {
      events.push((event as CustomEvent<{ id: string }>).detail.id);
    };
    document.addEventListener(THEME_EVENT, heard);
    const engine = createThemeEngine({
      themes: SHEET_PAGE,
      storage: memoryStorage(),
      win: null,
      loadSheet: sheets.load,
    });
    const tried = engine.previewTheme('snowball');
    // Until it has loaded, the page is as it was.
    expect(engine.current).toBe('midnight');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(sheets.asked).toEqual([{ href: SHEET, family: 'Fredoka Variable' }]);
    await sheets.finish(true);
    await expect(tried).resolves.toBe(true);
    expect(engine.current).toBe('snowball');
    expect(document.documentElement.dataset.theme).toBe('snowball');
    expect(document.getElementById(THEME_STYLE_ID)?.getAttribute('href')).toBe(SHEET);
    expect(bar()).toBe(themeOf('snowball').tokens.bg);
    expect(events).toEqual(['snowball']);
    engine.endPreview();
    expect(engine.current).toBe('midnight');
    expect(document.getElementById(THEME_STYLE_ID)).toBeNull();
    expect(bar()).toBe(MIDNIGHT_BAR);
    // The sheet stays in the page, unused, so the page's faces do not change as it goes, and the
    // theme goes on again at once, loading nothing.
    expect(spares()).toEqual([SHEET]);
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    await expect(engine.useTheme('snowball')).resolves.toBe(true);
    expect(sheets.asked).toHaveLength(1);
    expect(engine.current).toBe('snowball');
    expect(document.getElementById(THEME_STYLE_ID)?.getAttribute('href')).toBe(SHEET);
    expect(spares()).toEqual([]);
    expect(document.querySelectorAll('link[rel="stylesheet"]')).toHaveLength(1);
    // A theme of rules in its place keeps it too: one sheet, ever.
    await engine.useTheme('aurora');
    expect(sheetRules()).toBe(rulesOf('aurora').length);
    expect(spares()).toEqual([SHEET]);
    document.removeEventListener(THEME_EVENT, heard);
  });

  it('keeps unused a sheet that loads after a later change, and stays put where none loads', async () => {
    const sheets = loader();
    const storage = memoryStorage();
    const engine = createThemeEngine({
      themes: SHEET_PAGE,
      storage,
      win: null,
      loadSheet: sheets.load,
    });
    const stored = (): string | null => storage.getItem(THEME_STORAGE_KEY);
    const first = engine.useTheme('snowball');
    // Nothing is kept until it is on.
    expect(engine.kept).toBe('midnight');
    expect(stored()).toBeNull();
    await expect(engine.useTheme('aurora')).resolves.toBe(true);
    expect(engine.current).toBe('aurora');
    await sheets.finish(true);
    // A later change came first: the sheet is dropped, and Aurora stays on and kept.
    await expect(first).resolves.toBe(false);
    expect(engine.current).toBe('aurora');
    expect(engine.kept).toBe('aurora');
    expect(stored()).toBe(JSON.stringify({ id: 'aurora' }));
    expect(document.documentElement.dataset.theme).toBe('aurora');
    // Loaded, it stays unused in the page.
    expect(spares()).toEqual([SHEET]);
    // A sheet that cannot load: Aurora stays on and kept, and the call says Snowball is not on.
    for (const spare of document.querySelectorAll('link[rel="stylesheet"]')) spare.remove();
    const failed = engine.useTheme('snowball');
    await sheets.finish(false);
    await expect(failed).resolves.toBe(false);
    expect(engine.current).toBe('aurora');
    expect(engine.kept).toBe('aurora');
    expect(stored()).toBe(JSON.stringify({ id: 'aurora' }));
    expect(document.documentElement.dataset.theme).toBe('aurora');
    expect(document.querySelectorAll('link[rel="stylesheet"]')).toHaveLength(0);
    // A try that cannot load leaves no try behind: ending it changes nothing.
    const changes: unknown[] = [];
    engine.onChange((change) => changes.push(change));
    const tried = engine.previewTheme('snowball');
    await sheets.finish(false);
    await expect(tried).resolves.toBe(false);
    engine.endPreview();
    expect(changes).toEqual([]);
    // And one that loads is kept as it goes on, in the frame it goes on.
    const kept = engine.useTheme('snowball');
    expect(engine.kept).toBe('aurora');
    await sheets.finish(true);
    await expect(kept).resolves.toBe(true);
    expect(engine.current).toBe('snowball');
    expect(engine.kept).toBe('snowball');
    expect(stored()).toBe(JSON.stringify({ id: 'snowball' }));
    expect(changes).toEqual([{ id: 'snowball', preview: false }]);
  });

  it('ends a try still loading: the kept theme stays, and the try never goes on', async () => {
    const sheets = loader();
    const engine = createThemeEngine({
      themes: SHEET_PAGE,
      storage: memoryStorage(),
      win: null,
      loadSheet: sheets.load,
    });
    await engine.useTheme('glacier');
    const tried = engine.previewTheme('snowball');
    engine.endPreview();
    await sheets.finish(true);
    await expect(tried).resolves.toBe(false);
    expect(engine.current).toBe('glacier');
    expect(document.documentElement.dataset.theme).toBe('glacier');
    expect(spares()).toEqual([SHEET]);
  });

  it('tries again a kept sheet index.html could not load, and keeps Midnight where it fails', async () => {
    const sheets = loader();
    const storage = memoryStorage();
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ id: 'snowball' }));
    // index.html's first script, its sheet gone: Midnight's page and bar, and the mark.
    document.documentElement.setAttribute(THEME_RETRY, '');
    const engine = createThemeEngine({
      themes: SHEET_PAGE,
      storage,
      win: null,
      loadSheet: sheets.load,
    });
    expect(document.documentElement.hasAttribute(THEME_RETRY)).toBe(false);
    expect(sheets.asked).toEqual([{ href: SHEET, family: 'Fredoka Variable' }]);
    expect(engine.current).toBe('midnight');
    // It fails again: Midnight stays, bar and all, and Snowball stays kept for the next visit.
    await sheets.finish(false);
    expect(engine.current).toBe('midnight');
    expect(engine.kept).toBe('snowball');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(bar()).toBe(MIDNIGHT_BAR);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe(JSON.stringify({ id: 'snowball' }));
    // Where it loads, Snowball goes on.
    const again = createThemeEngine({
      themes: SHEET_PAGE,
      storage,
      win: null,
      loadSheet: sheets.load,
    });
    await sheets.finish(true);
    expect(again.current).toBe('snowball');
    expect(document.documentElement.dataset.theme).toBe('snowball');
    expect(bar()).toBe(themeOf('snowball').tokens.bg);
  });

  it('takes over the sheet index.html put on, loading nothing again', async () => {
    const sheets = loader();
    const storage = memoryStorage();
    storage.setItem(THEME_STORAGE_KEY, JSON.stringify({ id: 'snowball' }));
    const link = document.createElement('link');
    link.id = THEME_STYLE_ID;
    link.rel = 'stylesheet';
    link.setAttribute('href', SHEET);
    document.head.append(link);
    document.documentElement.setAttribute('data-theme', 'snowball');
    const engine = createThemeEngine({
      themes: SHEET_PAGE,
      storage,
      win: null,
      loadSheet: sheets.load,
    });
    expect(engine.current).toBe('snowball');
    expect(sheets.asked).toEqual([]);
    await expect(engine.useTheme('snowball')).resolves.toBe(true);
    expect(sheets.asked).toEqual([]);
    expect(document.getElementById(THEME_STYLE_ID)).toBe(link);
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

  it.each(THEME_IDS)(
    'never takes a word’s halo away in %s without a card that renders under it',
    (id) => {
      /** The theme's rules outside any media query, by selector. */
      const rules = new Map<string, string>();
      for (const rule of rulesOf(id)) {
        if (rule.startsWith('@')) continue;
        const open = rule.indexOf('{');
        const body = rule.slice(open + 1, rule.lastIndexOf('}'));
        for (const part of rule.slice(0, open).split(','))
          rules.set(part.trim(), `${rules.get(part.trim()) ?? ''};${body}`);
      }
      for (const [selector, body] of rules) {
        if (!body.includes('text-shadow:none') || selector.includes('::')) continue;
        // Whole in the theme's own rules, so it never leans on a card the page may not draw.
        const card = rules.get(`${selector}::before`) ?? '';
        expect(card, selector).toContain("content:''");
        expect(card, selector).toContain('position:absolute');
        expect(card, selector).toContain('z-index:-1');
        expect(card, selector).toMatch(/background:var\(--surface-[12]\)/);
      }
      // The update time can wrap past its card (a long line on a phone): it keeps its halo.
      expect(rules.get(`:root[data-theme='${id}'] .updated`) ?? '').not.toContain(
        'text-shadow:none',
      );
    },
  );
});

/**
 * The theme engine: puts a theme on the whole page at once, with no reload.
 *
 * A theme is one style sheet of custom properties and rules (css.ts), put
 * in rule by rule, and the root's data-theme attribute; the map takes its
 * colors from the same properties when the engine says so (event.ts
 * THEME_EVENT). Colors change and nothing moves: no theme changes a box's size.
 *
 * Every theme's CSS comes from the page (page.ts): the build writes the
 * themes it may show into index.html, whose first script puts the kept one on
 * before the first paint, and this module, which loads after it, takes over.
 * A theme with a style sheet of its own (Snowball) is loaded from it only
 * where it goes on or is tried: the page changes once that sheet and its face
 * have loaded, in one frame, and only then is it kept; once loaded, the
 * sheet stays in the page, unused while another theme is on (SPARE_SHEET),
 * so the theme goes on again at once and the page's faces never change as
 * it goes. If it cannot load,
 * nothing changes and nothing is kept: useTheme says so (false), and a page
 * never shows one theme while keeping another it was asked to put on.
 * A device keeps only the theme's id (THEME_STORAGE_KEY), so a new build's
 * page always shows its own version of the theme, and a theme that build may
 * not show is never on it: that page shows Midnight and leaves the id kept,
 * since tabs of an older and a newer build run side by side (an update waits
 * for its tab to be hidden), and the newer one may have just put it on. The
 * game (the account's equipped theme) tells the engine with useTheme (hook.ts equipTheme); the shop's "Try it" with
 * previewTheme, which keeps nothing. Another tab's change is followed.
 *
 * Midnight, the page's own CSS, is the default. A theme not yet released
 * (ids.ts THEMES_UNRELEASED) is never put on, unless this build names it
 * in VITE_THEMES_PREVIEW.
 */
import { THEME_EVENT, THEME_RETRY, THEME_STORAGE_KEY } from './event';
import { readPageThemes, type PageTheme, type PageThemes } from './page';
// The ids alone: no theme's palette is in this module's code (ids.ts).
import { DEFAULT_THEME, THEMES_UNRELEASED, isThemeId, type ThemeId } from './ids';

export { THEME_EVENT } from './event';
export type { ThemeId } from './ids';

/** The <style> a theme's CSS goes in; index.html's first script names it the same. */
export const THEME_STYLE_ID = 'sl-theme';

/** The bar color with Midnight, as index.html has it. */
export const MIDNIGHT_BAR = '#000000';

/** What a device keeps: the theme's id. */
export interface StoredTheme {
  readonly id: ThemeId;
}

export interface ThemeChange {
  readonly id: ThemeId;
  /** True while a theme is only being tried (previewTheme). */
  readonly preview: boolean;
}

/** The unreleased themes this build may show (VITE_THEMES_PREVIEW). */
function previewed(): ReadonlySet<string> {
  const names = import.meta.env.VITE_THEMES_PREVIEW ?? '';
  return new Set(
    names
      .split(',')
      .map((name) => name.trim())
      .filter((name) => name !== ''),
  );
}

/** Whether this build may put a theme on: every released one, and an unreleased one it names. */
export function themeAvailable(id: ThemeId): boolean {
  return isThemeId(id) && (!THEMES_UNRELEASED.has(id) || previewed().has(id));
}

/**
 * The mark on a theme's own style sheet that has loaded and is not on: it
 * stays in the page, unused (every rule of it is scoped to its theme's
 * data-theme), for the theme to go on again at once. Taking it out would
 * change the page's faces (its @font-face rules) as it goes and as it comes
 * back, and the browser lays out the page's words again each time: a word
 * on the map's bar can be seen to move (e2e/app.spec.ts).
 */
export const SPARE_SHEET = 'data-theme-spare';

/** Takes the theme on the page off: its <style> out, or its own style sheet kept, unused. */
function takeOff(doc: Document, keep: Element | null = null): void {
  const on = doc.getElementById(THEME_STYLE_ID);
  if (on === null || on === keep) return;
  if (on.tagName === 'LINK') {
    on.removeAttribute('id');
    on.setAttribute(SPARE_SHEET, '');
  } else on.remove();
}

/** A theme's own style sheet at `href` that has loaded: on the page, or kept unused. */
function loadedSheet(doc: Document, href: string): Element | null {
  for (const link of doc.querySelectorAll(`link#${THEME_STYLE_ID}, link[${SPARE_SHEET}]`)) {
    if (link.getAttribute('href') === href) return link;
  }
  return null;
}

/**
 * Puts `rules` in the page's theme sheet, a new one in place of what was
 * there (index.html's, or the last theme's). A rule this browser cannot read
 * is left out, and the rest stand.
 */
function putRules(doc: Document, rules: readonly string[]): void {
  takeOff(doc);
  if (rules.length === 0) return;
  const style = doc.createElement('style');
  style.id = THEME_STYLE_ID;
  doc.head.append(style);
  const sheet = style.sheet;
  if (sheet === null) return;
  for (const rule of rules) {
    try {
      sheet.insertRule(rule, sheet.cssRules.length);
    } catch {
      // Not this browser's CSS: the theme goes on without it.
    }
  }
}

/**
 * Loads a theme's own style sheet at `href` into the page, unused until the
 * theme goes on, and then `family`, its face: resolves with the sheet's
 * element, or null where it cannot load.
 */
export type SheetLoader = (
  doc: Document,
  href: string,
  family: string | undefined,
) => Promise<Element | null>;

/** How long a theme waits for its face before it goes on without it, in ms. */
export const FACE_WAIT_MS = 3000;

/** The page's own loader: a <link> in its head, and the face through its fonts. */
export const sheetLoader: SheetLoader = async (doc, href, family) => {
  const link = doc.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  const loaded = await new Promise<boolean>((resolve) => {
    link.addEventListener('load', () => {
      resolve(true);
    });
    link.addEventListener('error', () => {
      resolve(false);
    });
    doc.head.append(link);
  });
  if (!loaded) {
    link.remove();
    return null;
  }
  // Its words set in their own face from the frame it goes on: none moves as the face loads.
  const fonts = (doc as { fonts?: FontFaceSet }).fonts;
  if (family !== undefined && fonts !== undefined) {
    await Promise.race([
      fonts.load(`1em '${family}'`).catch(() => []),
      new Promise((resolve) => setTimeout(resolve, FACE_WAIT_MS)),
    ]);
  }
  return link;
};

/** The id a kept value names, or null. */
function storedId(raw: string | null): ThemeId | null {
  try {
    if (raw === null) return null;
    const stored = JSON.parse(raw) as Partial<StoredTheme> | null;
    return isThemeId(stored?.id) ? stored.id : null;
  } catch {
    return null;
  }
}

function readStored(storage: Storage | null): ThemeId | null {
  try {
    return storedId(storage?.getItem(THEME_STORAGE_KEY) ?? null);
  } catch {
    return null;
  }
}

function writeStored(storage: Storage | null, id: ThemeId): void {
  try {
    if (id === DEFAULT_THEME) storage?.removeItem(THEME_STORAGE_KEY);
    else storage?.setItem(THEME_STORAGE_KEY, JSON.stringify({ id } satisfies StoredTheme));
  } catch {
    // Private mode or a full store: the theme holds for this visit.
  }
}

function localStore(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export interface ThemeEngine {
  /** The theme on the page now, tried or kept. */
  readonly current: ThemeId;
  /** The theme kept on the device: what the page goes back to after a try. */
  readonly kept: ThemeId;
  /**
   * Puts a theme on and keeps it (the account's equipped theme, or a free
   * theme picked on the device); null goes back to Midnight. Resolves true
   * once it is on the page and kept: at once, or, for a theme with a style
   * sheet of its own, once that sheet and its face have loaded. Resolves
   * false, keeping nothing and changing nothing, where this build may not
   * show it, where its sheet cannot load, or where a later change came
   * first.
   */
  useTheme(id: ThemeId | null): Promise<boolean>;
  /** Puts a theme on for a look, keeping nothing (the shop's "Try it"): resolves as useTheme. */
  previewTheme(id: ThemeId): Promise<boolean>;
  /** Ends a try, or one still loading: back to the kept theme, dropping any change still loading. */
  endPreview(): void;
  /** Calls `listener` after every change; returns a function that stops it. */
  onChange(listener: (change: ThemeChange) => void): () => void;
}

export interface EngineOptions {
  readonly doc?: Document;
  readonly storage?: Storage | null;
  /** The themes the page carries; the page's own (page.ts) by default. */
  readonly themes?: PageThemes;
  /** Where another tab's change is heard: the page's window by default. */
  readonly win?: Pick<Window, 'addEventListener'> | null;
  /** How a theme's own style sheet is loaded (sheetLoader by default). */
  readonly loadSheet?: SheetLoader;
}

/**
 * Starts the engine on the page: takes over the theme index.html put on
 * from the device's store, or shows Midnight where this build may not show
 * the kept theme, which stays kept: a page writes the store only when
 * useTheme is called, never because it does not know a theme.
 */
export function createThemeEngine({
  doc = document,
  storage = localStore(),
  themes = readPageThemes(doc),
  win = typeof window === 'undefined' ? null : window,
  loadSheet = sheetLoader,
}: EngineOptions = {}): ThemeEngine {
  const listeners = new Set<(change: ThemeChange) => void>();
  /** Whether this build may show `id` and the page carries it. */
  const shown = (id: ThemeId): boolean =>
    id === DEFAULT_THEME || (themeAvailable(id) && themes[id] !== undefined);
  const stored = readStored(storage);
  let kept: ThemeId = stored !== null && shown(stored) ? stored : DEFAULT_THEME;
  let current: ThemeId = DEFAULT_THEME;
  /** Whether the theme on the page is only being tried. */
  let preview = false;
  /** How the last change asked for goes on: kept, tried, or as the device keeps it. */
  type Way = 'keep' | 'try' | 'follow';
  let asking: Way = 'follow';

  /** How many changes were asked for: a sheet that loads after a later change is dropped. */
  let asked = 0;

  /**
   * Puts `id` on in this frame, the way it was asked for: its rules, or
   * `sheet`, its style sheet, already loaded. A theme asked to be kept is
   * kept here, as it goes on, and never before.
   */
  const show = (
    id: ThemeId,
    page: PageTheme | undefined,
    sheet: Element | null,
    way: Way,
  ): void => {
    const root = doc.documentElement;
    if (sheet === null) putRules(doc, page?.rules ?? []);
    else {
      takeOff(doc, sheet);
      sheet.removeAttribute(SPARE_SHEET);
      sheet.id = THEME_STYLE_ID;
    }
    if (page === undefined) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', id);
    // The browser's bar over the page in the theme's ground.
    doc
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', page?.color ?? MIDNIGHT_BAR);
    if (way === 'keep') {
      kept = id;
      writeStored(storage, id);
    }
    preview = way === 'try';
    const changed = id !== current;
    current = id;
    if (changed || page !== undefined) {
      doc.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { id, preview } }));
    }
    for (const listener of listeners) listener({ id, preview });
  };

  /**
   * Puts `id` on, the way asked: at once, or, for a theme with a style sheet
   * of its own, once that sheet and its face have loaded, with the page as
   * it was until then, so it changes once, in one frame. Resolves whether it
   * went on: where the sheet cannot load, or a later change came first, the
   * page stays as it is and nothing is kept.
   */
  const apply = (id: ThemeId, way: Way): Promise<boolean> => {
    asked += 1;
    asking = way;
    const ticket = asked;
    const page = id === DEFAULT_THEME ? undefined : themes[id];
    if (page?.sheet === undefined) {
      show(id, page, null, way);
      return Promise.resolve(true);
    }
    // On the page already (index.html's, or loaded before and kept): on at once.
    const loaded = loadedSheet(doc, page.sheet);
    if (loaded !== null) {
      show(id, page, loaded, way);
      return Promise.resolve(true);
    }
    return loadSheet(doc, page.sheet, page.family).then((sheet) => {
      if (sheet === null) {
        // Nothing went on: what the page shows is what it was asked before.
        if (ticket === asked) asking = preview ? 'try' : 'follow';
        return false;
      }
      if (ticket === asked) {
        show(id, page, sheet, way);
        return true;
      }
      // A later change came first: the sheet stays, unused, for the theme to go on at once.
      if (sheet !== doc.getElementById(THEME_STYLE_ID)) sheet.setAttribute(SPARE_SHEET, '');
      return false;
    });
  };

  /** Whether a try is on the page, or one is still loading. */
  const trying = (): boolean => preview || asking === 'try';

  // index.html could not load a kept theme's style sheet (event.ts THEME_RETRY): tried again below.
  doc.documentElement.removeAttribute(THEME_RETRY);
  // What index.html put on, from this same page's themes, is the kept theme already: the engine
  // takes it over as it is, with no second sheet and no restyle. Anything else, it puts right.
  const onPage = doc.documentElement.getAttribute('data-theme');
  current = isThemeId(onPage) ? onPage : DEFAULT_THEME;
  const putOn =
    current === kept && (kept === DEFAULT_THEME || doc.getElementById(THEME_STYLE_ID) !== null);
  if (!putOn) void apply(kept, 'follow');
  // Nothing is written here: a kept theme this build does not show stays kept, as another tab on
  // a newer build may have just put it on (only useTheme keeps a theme, or ends one).

  // Another tab kept another theme (the game equipped one there): this one follows, after a try.
  win?.addEventListener('storage', (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    const next = event.key === null ? null : storedId(event.newValue);
    const id = next !== null && shown(next) ? next : DEFAULT_THEME;
    if (id === kept) return;
    kept = id;
    if (!trying()) void apply(id, 'follow');
  });

  return {
    get current() {
      return current;
    },
    get kept() {
      return kept;
    },
    useTheme(id) {
      const next = id ?? DEFAULT_THEME;
      if (!shown(next)) return Promise.resolve(false);
      return apply(next, 'keep');
    },
    previewTheme(id) {
      if (!shown(id)) return Promise.resolve(false);
      return apply(id, 'try');
    },
    endPreview() {
      if (!trying()) return;
      void apply(kept, 'follow');
    },
    onChange(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

let engine: ThemeEngine | null = null;

/**
 * The page's one engine, started on first use (app/boot.ts starts it after
 * the first paint). Under automation the page also hands it to tests as
 * window.snowlightTheme.
 */
export function themeEngine(): ThemeEngine {
  engine ??= createThemeEngine();
  if (navigator.webdriver) (window as { snowlightTheme?: ThemeEngine }).snowlightTheme = engine;
  return engine;
}

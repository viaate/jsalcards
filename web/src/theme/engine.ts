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
 * A device keeps only the theme's id (THEME_STORAGE_KEY), so a new build's
 * page always shows its own version of the theme, and a theme that build may
 * not show is never on it: that page shows Midnight and leaves the id kept,
 * since tabs of an older and a newer build run side by side (an update waits
 * for its tab to be hidden), and the newer one may have just put it on. The game (the account's equipped theme) tells the
 * engine with useTheme (hook.ts equipTheme); the shop's "Try it" with
 * previewTheme, which keeps nothing. Another tab's change is followed.
 *
 * Midnight, the page's own CSS, is the default. A theme not yet released
 * (themes.ts THEMES_UNRELEASED) is never put on, unless this build names it
 * in VITE_THEMES_PREVIEW.
 */
import { THEME_EVENT, THEME_STORAGE_KEY } from './event';
import { readPageThemes, type PageThemes } from './page';
import {
  DEFAULT_THEME,
  THEMES,
  THEMES_UNRELEASED,
  THEME_IDS,
  isThemeId,
  type Theme,
  type ThemeId,
} from './themes';

export { THEME_EVENT } from './event';
export type { ThemeId } from './themes';

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
  return THEMES[id] !== undefined && (!THEMES_UNRELEASED.has(id) || previewed().has(id));
}

/** The themes a shop or a picker lists: every one this build may put on, in order. */
export function listedThemes(): readonly Theme[] {
  return THEME_IDS.filter(themeAvailable).flatMap((id) => THEMES[id] ?? []);
}

/**
 * Puts `rules` in the page's theme sheet, a new one in place of what was
 * there (index.html's, or the last theme's). A rule this browser cannot read
 * is left out, and the rest stand.
 */
function putRules(doc: Document, rules: readonly string[]): void {
  doc.getElementById(THEME_STYLE_ID)?.remove();
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
   * theme picked on the device); null goes back to Midnight. A theme this
   * build may not show is refused: false.
   */
  useTheme(id: ThemeId | null): boolean;
  /** Puts a theme on for a look, keeping nothing: the shop's "Try it". */
  previewTheme(id: ThemeId): boolean;
  /** Ends a try: back to the kept theme. */
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
}: EngineOptions = {}): ThemeEngine {
  const listeners = new Set<(change: ThemeChange) => void>();
  /** Whether this build may show `id` and the page carries it. */
  const shown = (id: ThemeId): boolean =>
    id === DEFAULT_THEME || (themeAvailable(id) && themes[id] !== undefined);
  const stored = readStored(storage);
  let kept: ThemeId = stored !== null && shown(stored) ? stored : DEFAULT_THEME;
  let current: ThemeId = DEFAULT_THEME;
  let preview = false;

  const apply = (id: ThemeId): void => {
    const page = id === DEFAULT_THEME ? undefined : themes[id];
    const root = doc.documentElement;
    putRules(doc, page?.rules ?? []);
    if (page === undefined) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', id);
    // The browser's bar over the page in the theme's ground.
    doc
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', page?.color ?? MIDNIGHT_BAR);
    const changed = id !== current;
    current = id;
    if (changed || page !== undefined) {
      doc.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { id, preview } }));
    }
    for (const listener of listeners) listener({ id, preview });
  };

  // What index.html put on, from this same page's themes, is the kept theme already: the engine
  // takes it over as it is, with no second sheet and no restyle. Anything else, it puts right.
  const onPage = doc.documentElement.getAttribute('data-theme');
  current = isThemeId(onPage) ? onPage : DEFAULT_THEME;
  const putOn =
    current === kept && (kept === DEFAULT_THEME || doc.getElementById(THEME_STYLE_ID) !== null);
  if (!putOn) apply(kept);
  // Nothing is written here: a kept theme this build does not show stays kept, as another tab on
  // a newer build may have just put it on (only useTheme keeps a theme, or ends one).

  // Another tab kept another theme (the game equipped one there): this one follows, after a try.
  win?.addEventListener('storage', (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    const next = event.key === null ? null : storedId(event.newValue);
    const id = next !== null && shown(next) ? next : DEFAULT_THEME;
    if (id === kept) return;
    kept = id;
    if (!preview) apply(id);
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
      if (!shown(next)) return false;
      kept = next;
      preview = false;
      writeStored(storage, next);
      apply(next);
      return true;
    },
    previewTheme(id) {
      if (!shown(id)) return false;
      preview = true;
      apply(id);
      return true;
    },
    endPreview() {
      if (!preview) return;
      preview = false;
      apply(kept);
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

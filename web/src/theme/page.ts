/**
 * The themes this build's page carries (index.html #sl-themes): each one it
 * may show, as this build writes its CSS (tools/themes.ts fills it in at build
 * time). index.html's first script puts the kept one on from it before the
 * first paint, and the engine (engine.ts) from it after, so a page only ever
 * shows its own build's version of a theme, and never one the build may not
 * show: a theme not in it is not on the page at all.
 */
import type { ThemeId } from './themes.ts';

/** The element whose JSON holds them, and the first script's. */
export const PAGE_THEMES_ID = 'sl-themes';

/** One theme as the page carries it. */
export interface PageTheme {
  /** Its CSS, rule by rule (theme/css.ts themeRules). */
  readonly rules: readonly string[];
  /** The bar color the browser shows over the page with it. */
  readonly color: string;
  /** A face its words are set in, to fetch first where it is kept (a toon theme's). */
  readonly font?: string;
}

export type PageThemes = Readonly<Partial<Record<ThemeId, PageTheme>>>;

function isPageTheme(value: unknown): value is PageTheme {
  if (typeof value !== 'object' || value === null) return false;
  const theme = value as { rules?: unknown; color?: unknown; font?: unknown };
  return (
    Array.isArray(theme.rules) &&
    theme.rules.every((rule) => typeof rule === 'string') &&
    typeof theme.color === 'string' &&
    (theme.font === undefined || typeof theme.font === 'string')
  );
}

/** A page, as far as reading its themes goes (the build reads this module too, with no DOM). */
interface ThemedPage {
  getElementById(id: string): { readonly textContent: string | null } | null;
}

/** The themes `doc` carries; none where it carries none or they cannot be read. */
export function readPageThemes(doc: ThemedPage): PageThemes {
  try {
    const parsed: unknown = JSON.parse(doc.getElementById(PAGE_THEMES_ID)?.textContent ?? '{}');
    if (typeof parsed !== 'object' || parsed === null) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, theme]) => isPageTheme(theme)));
  } catch {
    return {};
  }
}

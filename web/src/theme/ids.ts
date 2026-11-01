/**
 * The themes' ids, apart from their colors (themes.ts): what the engine
 * (engine.ts) needs to know which theme a device keeps and whether this build
 * may show it. The page gives the engine each theme's CSS or the address of
 * its own style sheet (page.ts), so the engine's code carries no theme's
 * palette: a theme's colors reach a device only in the CSS it puts on, or
 * with the shop (shop.ts), which draws every theme's tile.
 */
import { UNRELEASED_IDS, type UnreleasedThemeId } from './unreleased.ts';

export type { UnreleasedThemeId } from './unreleased.ts';

/**
 * Whether this build's scripts carry the unreleased themes (unreleased.ts)
 * at all: vite.config.ts says so (__UNRELEASED_THEMES__), true only where
 * VITE_THEMES_PREVIEW names one, so a default build's scripts hold none of
 * them, not even a name: they leave them out as code never run. The build's
 * own tools and the tests, which run with no such word, carry them.
 */
declare const __UNRELEASED_THEMES__: boolean | undefined;
export const UNRELEASED_BUILT: boolean =
  typeof __UNRELEASED_THEMES__ === 'boolean' ? __UNRELEASED_THEMES__ : true;

const RELEASED = [
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
] as const;

/** Every theme's id, whether this build carries it or not. */
export type ThemeId = (typeof RELEASED)[number] | UnreleasedThemeId;

/** The themes this build carries, in the shop's order: an unreleased one last, where built. */
export const THEME_IDS: readonly ThemeId[] = UNRELEASED_BUILT
  ? [...RELEASED, ...UNRELEASED_IDS]
  : RELEASED;

/** The unreleased themes this build carries. */
export const THEMES_UNRELEASED: ReadonlySet<ThemeId> = new Set<ThemeId>(
  UNRELEASED_BUILT ? UNRELEASED_IDS : [],
);

/** The theme a first visit gets, and the one the page's own CSS draws. */
export const DEFAULT_THEME: ThemeId = 'midnight';

/** An id this build carries. */
export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

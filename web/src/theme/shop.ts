/**
 * The themes the shop lists, each with its colors for its tile
 * (ui/themes/ThemeTile.svelte): every one this build may put on, in the
 * shop's order. The one module a page loads the themes' palettes with
 * (themes.ts): the shop imports it when it opens, never the engine, so a
 * device that never opens the shop has no theme's palette but the one it
 * puts on, and that only as CSS.
 */
import { themeAvailable } from './engine';
import { THEMES, THEME_IDS, type Theme } from './themes';

export function listedThemes(): readonly Theme[] {
  return THEME_IDS.filter(themeAvailable).flatMap((id) => THEMES[id] ?? []);
}

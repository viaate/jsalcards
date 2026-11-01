/**
 * The themes built but not yet offered anywhere, until the owner approves
 * them: a build carries and lists them only where VITE_THEMES_PREVIEW names
 * one (for the owner's screenshots; themes.ts THEMES_UNRELEASED), and a
 * device that has one kept sees Midnight. A default build's scripts carry
 * nothing of this module (vite.config.ts). None waits at present: a theme
 * built for the owner's yes goes here, with its id in UNRELEASED_IDS, and
 * moves to themes.ts once released.
 */
import type { Theme } from './themes.ts';

/** The waiting themes' ids, in the order a preview build lists them after the released ones. */
const LISTED = [] as const;

/**
 * A waiting theme's id: one LISTED names, or, while none is listed, any id
 * of the `next-` form (a stand-in's, src/theme/tests/unreleased.test.ts), so
 * the gate's types and code hold with the list empty.
 */
export type UnreleasedThemeId = [(typeof LISTED)[number]] extends [never]
  ? `next-${string}`
  : (typeof LISTED)[number];

export const UNRELEASED_IDS: readonly UnreleasedThemeId[] = LISTED;

export const UNRELEASED_THEMES: Readonly<Record<UnreleasedThemeId, Theme>> = {};

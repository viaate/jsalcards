/**
 * Where a school's detail sheet opens on a phone, for the sheet itself
 * (ui/sheet.ts) and for the camera that puts the school in the middle of the
 * map it leaves in view (App.svelte). Kept apart from the sheet's own code, so
 * the page's first script carries only these few numbers.
 */

/** Screens this narrow show the panel as a sheet over the foot of the map (index.html's phone layout). */
export const PHONE_QUERY = '(max-width: 719px)';

/**
 * The share of the screen's height the sheet opens to: its name, today's
 * status and the chance of a closure above the fold, and half the screen
 * left to the map, with the school in the middle of it.
 */
export const OPEN_SHARE = 0.5;

/**
 * How much of a sheet opening now shows, in CSS pixels from the foot of the
 * screen: OPEN_SHARE of `screenHeight`, and no more than `fullHeight`, the
 * most it ever shows.
 */
export function openHeight(screenHeight: number, fullHeight = Infinity): number {
  return Math.max(0, Math.min(Math.round(screenHeight * OPEN_SHARE), fullHeight));
}

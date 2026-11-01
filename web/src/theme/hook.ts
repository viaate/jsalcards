/**
 * The game's hook for the account's equipped theme: the one call the game
 * lane makes, which loads the theme engine (engine.ts) the first time.
 *
 * - On sign-in, and whenever the account equips a theme, call
 *   equipTheme(id): the page changes and the device keeps the id, so its
 *   next visit paints in it from the first frame (index.html). The page
 *   changes at once, or, for a theme with a style sheet of its own
 *   (Snowball), once that sheet and its face have loaded, and only then is
 *   the id kept: await the result before showing the theme as in use. On a
 *   device that has never kept it, the page first paints in the theme it
 *   keeps (Midnight on a new one) and changes once the account is read:
 *   nothing on the page knows the account before then.
 * - On sign-out, call equipTheme(null): back to Midnight, and the device
 *   keeps nothing, so the next visit is Midnight too. A free theme picked on
 *   the device itself is equipTheme(id) as well.
 * - Every open tab follows (engine.ts): no other call is needed.
 *
 * Resolves true once the theme is on the page and kept. Resolves false, and
 * nothing changes and nothing is kept, where this build may not show the
 * theme (one waiting for the owner's approval), where its style sheet cannot
 * load (offline, say), or where a later call came first: the page goes on
 * showing the theme it showed, so the game never marks a theme in use that
 * the page does not show.
 */
import type { ThemeId } from './ids';

export async function equipTheme(id: ThemeId | null): Promise<boolean> {
  const { themeEngine } = await import('./engine');
  return themeEngine().useTheme(id);
}

/**
 * The game's hook for the account's equipped theme: the one call the game
 * lane makes, which loads the theme engine (engine.ts) the first time.
 *
 * - On sign-in, and whenever the account equips a theme, call
 *   equipTheme(id): the page changes at once and the device keeps the id,
 *   so its next visit paints in it from the first frame (index.html). On a
 *   device that has never kept it, the page first paints in the theme it
 *   keeps (Midnight on a new one) and changes once the account is read:
 *   nothing on the page knows the account before then.
 * - On sign-out, call equipTheme(null): back to Midnight, and the device
 *   keeps nothing, so the next visit is Midnight too. A free theme picked on
 *   the device itself is equipTheme(id) as well.
 * - Every open tab follows (engine.ts): no other call is needed.
 *
 * Resolves false where this build may not show the theme (one waiting for
 * the owner's approval), and nothing changes.
 */
import type { ThemeId } from './themes';

export async function equipTheme(id: ThemeId | null): Promise<boolean> {
  const { themeEngine } = await import('./engine');
  return themeEngine().useTheme(id);
}

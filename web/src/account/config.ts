/**
 * The accounts API this build talks to (VITE_API_ROOT, set by preview.yml from
 * the Cloudflare account or the SNOWLIGHT_API_ROOT variable), or null: then the
 * page has no account controls at all. Kept tiny: the page's first script
 * carries it, and the account code itself loads after the first paint.
 */

import { checkApiRoot } from './root';

/** The API root without a trailing slash, or null when this build has none. */
export function apiRoot(
  raw: string | undefined = import.meta.env.VITE_API_ROOT,
  loopback: boolean = import.meta.env.VITE_API_LOOPBACK === '1',
): string | null {
  return checkApiRoot(raw, loopback);
}

/** Whether the address asks for the admin view (?admin). */
export function asksForAdmin(search: string = location.search): boolean {
  try {
    return new URLSearchParams(search).has('admin');
  } catch {
    return false;
  }
}

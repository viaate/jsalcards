/**
 * The Gmail demo's grant, if a read was cut off (flights spec D19 GOOGLE RULE; SAFE-R3-S3). While
 * a read runs, its short-lived token sits in this tab's sessionStorage, for this one purpose: a
 * read that a reload cut short leaves it there, and the next page load (or the next read) asks
 * Google to revoke it, so no Gmail read grant is left standing. A closed tab takes its
 * sessionStorage with it: that grant the person removes in their Google account (GOOGLE-SETUP.md).
 */
export const LEFTOVER_KEY = 'snowlight-gmail-demo';
const REVOKE = 'https://oauth2.googleapis.com/revoke';

function store(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/**
 * The tokens of the reads running in this page now (SAFE-R4-S2, SAFE-R5-S2): never leftovers, so a
 * My trips reopened while one runs does not cut it off. Each read keeps and drops only its own
 * token, and the stored list holds every one still running, so two reads at once (My trips closed
 * and opened again in between) each stay revocable after a reload. Only tokens an earlier page
 * load left are revoked.
 */
const running = new Set<string>();

/** The stored tokens: a list (one plain token is read as a list of one). */
function stored(): string[] | null {
  let raw: string | null;
  try {
    raw = store()?.getItem(LEFTOVER_KEY) ?? null;
  } catch {
    return null;
  }
  if (raw === null || raw === '') return [];
  if (!raw.startsWith('[')) return [raw];
  try {
    const list: unknown = JSON.parse(raw);
    return Array.isArray(list)
      ? list.filter((item): item is string => typeof item === 'string' && item !== '')
      : [];
  } catch {
    return [];
  }
}

function save(tokens: readonly string[]): void {
  try {
    if (tokens.length === 0) store()?.removeItem(LEFTOVER_KEY);
    else store()?.setItem(LEFTOVER_KEY, JSON.stringify(tokens));
  } catch {
    // No storage: a cut-off read is then left to the person (see above).
  }
}

/** Keeps a running read's token until it is revoked (with any other read's still kept). */
export function keepLeftover(token: string): void {
  running.add(token);
  const tokens = stored() ?? [];
  save(tokens.includes(token) ? tokens : [...tokens, token]);
}

/** That read is done and its grant revoked: only its own token is dropped. */
export function dropLeftover(token: string): void {
  running.delete(token);
  save((stored() ?? []).filter((kept) => kept !== token));
}

/** Revokes the tokens cut-off reads left, if any; nothing happens otherwise. */
export async function revokeLeftover(
  fetcher: typeof fetch = (...args) => fetch(...args),
): Promise<boolean> {
  const tokens = stored();
  if (tokens === null) return false;
  const left = tokens.filter((token) => !running.has(token));
  if (left.length === 0) return false;
  save(tokens.filter((token) => running.has(token)));
  for (const token of left) {
    try {
      // A plain form POST, as Google's own revoke sends it; the answer is not read.
      await fetcher(REVOKE, {
        method: 'POST',
        mode: 'no-cors',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ token }).toString(),
      });
    } catch {
      // Offline: the grant stays at Google until the person removes it.
    }
  }
  return true;
}

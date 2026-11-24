/**
 * The demo-only Find my flights in Gmail (flights spec D19, GOOGLE RULE). Loaded only when the
 * person presses it, and only shown while the API's GMAIL_READ_DEMO flag is on and Google is set
 * up. It asks Google for gmail.readonly on its own, with a short-lived token from Google Identity
 * Services' token client (the client id alone, no secret), searches only airline confirmation
 * emails from the last 6 months, and parses them here on the device (gmail.ts). Nothing from the
 * email goes to the accounts API or anywhere else: only the trip fields the person confirms are
 * saved, as typing them does. The token is kept nowhere but this tab's sessionStorage while the
 * read runs, so a read a reload cut short is revoked on the next load (gmail-leftover.ts). It
 * asks for gmail.readonly alone
 * (include_granted_scopes off), so it never carries Connect Google's scopes.
 *
 * ITS OWN CLIENT: the read uses the demo's own OAuth client id (GMAIL_DEMO_CLIENT_ID, in its own
 * Google Cloud project), never Connect Google's. Google's revoke ends every scope a person gave
 * one client, so on a shared client it would end a Connect Google link, this account's or
 * another's. On its own client, the read always revokes its grant when it is done: no Gmail read
 * grant is left standing, and no link is touched.
 */
import type { Airport } from './data';
import type { FoundFlight } from './found';
import { flightsInEmail } from './gmail';
import { dropLeftover, keepLeftover, revokeLeftover } from './gmail-leftover';

const GIS = 'https://accounts.google.com/gsi/client';
const SCOPE = 'https://www.googleapis.com/auth/gmail.readonly';
const GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages';
/** Only airline confirmations, from the last 6 months. */
export const QUERY =
  'newer_than:6m (subject:(confirmation OR itinerary OR receipt OR "your trip") (flight OR airlines OR airways))';
const MAX_EMAILS = 25;

interface TokenClient {
  requestAccessToken(): void;
}

interface Gis {
  accounts: {
    oauth2: {
      initTokenClient(config: {
        client_id: string;
        scope: string;
        include_granted_scopes?: boolean;
        callback: (answer: { access_token?: string; error?: string }) => void;
        error_callback?: (error: unknown) => void;
      }): TokenClient;
      revoke(token: string, done?: () => void): void;
    };
  };
}

function gis(): Promise<Gis> {
  const ready = (window as { google?: Gis }).google;
  if (ready !== undefined) return Promise.resolve(ready);
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = GIS;
    script.async = true;
    script.onload = () => {
      const loaded = (window as { google?: Gis }).google;
      if (loaded === undefined) reject(new Error('gis'));
      else resolve(loaded);
    };
    script.onerror = () => {
      reject(new Error('gis'));
    };
    document.head.append(script);
  });
}

function token(google: Gis, clientId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const client = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: SCOPE,
      include_granted_scopes: false,
      callback: (answer) => {
        if (typeof answer.access_token === 'string' && answer.access_token !== '')
          resolve(answer.access_token);
        else reject(new Error('denied'));
      },
      error_callback: () => {
        reject(new Error('denied'));
      },
    });
    client.requestAccessToken();
  });
}

function decode(data: string): string {
  const binary = atob(data.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

interface Part {
  mimeType?: string;
  body?: { data?: string };
  parts?: Part[];
}

/** The email's HTML part (or its text), decoded. */
export function htmlOf(part: Part | undefined, depth = 0): string {
  if (part === undefined || depth > 6) return '';
  if (part.mimeType === 'text/html' && typeof part.body?.data === 'string')
    return decode(part.body.data);
  for (const child of part.parts ?? []) {
    const html = htmlOf(child, depth + 1);
    if (html !== '') return html;
  }
  if (part.mimeType === 'text/plain' && typeof part.body?.data === 'string')
    return decode(part.body.data);
  return '';
}

/**
 * The flights in the person's airline confirmation emails, read on this device. `clientId`: the
 * demo's own client (see above), whose grant is revoked at the end, whatever happens.
 */
export async function readGmail(
  clientId: string,
  airports: ReadonlyMap<string, Airport>,
  fetcher: typeof fetch = (...args) => fetch(...args),
): Promise<FoundFlight[]> {
  await revokeLeftover(fetcher);
  const google = await gis();
  const access = await token(google, clientId);
  keepLeftover(access);
  try {
    const headers = { Authorization: `Bearer ${access}` };
    const list = await fetcher(
      `${GMAIL}?maxResults=${String(MAX_EMAILS)}&q=${encodeURIComponent(QUERY)}`,
      { headers, cache: 'no-store' },
    );
    if (!list.ok) throw new Error('gmail');
    const { messages = [] } = (await list.json()) as { messages?: { id: string }[] };
    const found: FoundFlight[] = [];
    for (const { id } of messages.slice(0, MAX_EMAILS)) {
      const response = await fetcher(`${GMAIL}/${encodeURIComponent(id)}?format=full`, {
        headers,
        cache: 'no-store',
      });
      if (!response.ok) continue;
      const message = (await response.json()) as { payload?: Part };
      for (const flight of flightsInEmail({ html: htmlOf(message.payload) }, airports))
        if (
          !found.some(
            (f) =>
              f.carrier === flight.carrier && f.number === flight.number && f.day === flight.day,
          )
        )
          found.push(flight);
    }
    return found;
  } finally {
    google.accounts.oauth2.revoke(access);
    dropLeftover(access);
  }
}

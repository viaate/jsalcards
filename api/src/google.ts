/**
 * Connect Google (flights spec D12; docs/flights-trips.md): OAuth 2.0 authorization code with
 * PKCE (S256), through this Worker, for calendar.readonly (flights Gmail already put in Google
 * Calendar) and gmail.send (the alert email, from the person's own Gmail to themselves).
 *
 * DORMANT UNTIL CONFIGURED: with GOOGLE_CLIENT_ID (a var) and GOOGLE_CLIENT_SECRET (a secret)
 * both set, GET /v1/google/config says configured; until then it says not, every other Google
 * route answers 404 google_off, and the page shows no Google option at all.
 *
 * The flow: the signed-in page asks POST /v1/me/google/start for Google's address (a fresh state
 * and PKCE verifier kept here for 10 minutes, the state only as its SHA-256). Google sends the
 * person back to the site's own /google.html, which hands the code and state to the signed-in
 * page, which sends them to POST /v1/me/google/finish with its session: the state must be one
 * this same account started (so a connect started by someone else can never land in this
 * account), and is used once. The refresh token is kept encrypted (AES-GCM, a key derived with
 * HKDF from the client secret, the account id as additional data); the access tokens are never
 * kept. Disconnect and account deletion delete it and ask Google to revoke it.
 *
 * CPU: each route is a few D1 statements, one SHA-256, one HKDF and one AES-GCM over a few
 * hundred bytes, and at most two small calls to Google (time spent waiting on the network is not
 * CPU). The calendar import asks Google for at most 50 events with only the fields it reads.
 */

import { readAlert } from '../../web/src/modes/flights/alert.ts';
import { alertEmail } from '../../web/src/copy-trips.ts';
import { bucket, hit, hits, requireSession } from './auth';
import { HttpError, allowedOrigin, json, readBody, type Env } from './http';
import { b64url, fromB64url, randomBytes, secretEqual, sha256 } from './util';

export const GOOGLE = Object.freeze({
  auth: 'https://accounts.google.com/o/oauth2/v2/auth',
  token: 'https://oauth2.googleapis.com/token',
  revoke: 'https://oauth2.googleapis.com/revoke',
  events: 'https://www.googleapis.com/calendar/v3/calendars/primary/events',
  send: 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
});

export const SCOPE_CALENDAR = 'https://www.googleapis.com/auth/calendar.readonly';
export const SCOPE_SEND = 'https://www.googleapis.com/auth/gmail.send';
export const SCOPES = ['openid', 'email', SCOPE_CALENDAR, SCOPE_SEND] as const;
export const STATE_MS = 10 * 60_000;
/** Connects in progress an account may have at once. */
const MAX_STATES = 5;
/** Calendar reads per account per hour. */
const CALENDAR_PER_HOUR = 20;
/** How far ahead the calendar is read. */
export const CALENDAR_DAYS = 60;
export const MAX_EVENTS = 50;
/** The page Google sends the person back to, on the site's own origin. */
export const RETURN_PATH = '/google.html';
/** The settings row that holds the sender's key (SHA-256 hex and its end, in ms). */
export const MAIL_KEY = 'flights_mail_key';

const STATE = /^[A-Za-z0-9_-]{43}$/;
const BASE = /^\/(?:[A-Za-z0-9_-]{1,40}\/){0,2}$/;
const EMAIL = /^[^\s@<>()",;:\\[\]]{1,64}@[A-Za-z0-9.-]{1,190}$/;
const USER_ID = /^[0-9a-f]{32}$/;
const SUB = /^[A-Za-z0-9_-]{1,255}$/;
/** A Google client in Testing mode ends its refresh tokens after 7 days: a link older than this
 * is checked with Google when the page asks (at most every RECHECK_MS), so it never reads as
 * connected on a token that is gone. */
const CHECK_AFTER_MS = 6 * 86_400_000;
const RECHECK_MS = 6 * 3_600_000;
const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** Whether the owner has set up the Google client: both its id and its secret. */
export function configured(env: Env): boolean {
  const id = env.GOOGLE_CLIENT_ID?.trim() ?? '';
  const secret = env.GOOGLE_CLIENT_SECRET?.trim() ?? '';
  return id.length > 0 && id.length <= 256 && secret.length > 0;
}

function requireConfigured(env: Env): { id: string; secret: string } {
  if (!configured(env)) throw new HttpError(404, 'google_off');
  return {
    id: (env.GOOGLE_CLIENT_ID ?? '').trim(),
    secret: (env.GOOGLE_CLIENT_SECRET ?? '').trim(),
  };
}

/**
 * The Gmail demo's own client id, or null: shown only with the flag on, Google set up, and a
 * client of its own (flights spec D19). Google's revoke ends every scope a person gave one
 * client (one project), so a demo on Connect Google's client could end its link, or another
 * Snowlight account's link to the same Google account, and would leave a Gmail read grant on it.
 */
export function gmailDemoClient(env: Env): string | null {
  if (!configured(env) || env.GMAIL_READ_DEMO !== '1') return null;
  const id = env.GMAIL_DEMO_CLIENT_ID?.trim() ?? '';
  if (id.length === 0 || id.length > 256 || id === (env.GOOGLE_CLIENT_ID ?? '').trim()) return null;
  return id;
}

/** GET /v1/google/config: whether Google is set up, its public client id, and the Gmail demo's. */
export function googleConfig(env: Env): Response {
  const on = configured(env);
  const demo = gmailDemoClient(env);
  return json(200, {
    configured: on,
    client_id: on ? (env.GOOGLE_CLIENT_ID ?? '').trim() : null,
    gmail_demo: demo !== null,
    gmail_client_id: demo,
  });
}

// Token encryption ----------------------------------------------------------------------------

/** The derived key, once per isolate and secret: HKDF is the costliest step of a request. */
const keys = new Map<string, Promise<CryptoKey>>();

function tokenKey(secret: string): Promise<CryptoKey> {
  let key = keys.get(secret);
  if (key === undefined) {
    key = deriveTokenKey(secret);
    keys.set(secret, key);
    // A failed derive is never kept.
    key.catch(() => keys.delete(secret));
  }
  return key;
}

async function deriveTokenKey(secret: string): Promise<CryptoKey> {
  const base = await crypto.subtle.importKey('raw', encoder.encode(secret), 'HKDF', false, [
    'deriveKey',
  ]);
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: encoder.encode('snowlight-google-token-v1'),
      info: encoder.encode('refresh-token'),
    },
    base,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

/** A refresh token sealed for one account: "v1.<iv>.<ciphertext>", base64url. */
export async function seal(secret: string, userId: string, token: string): Promise<string> {
  const iv = randomBytes(12);
  const sealed = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: encoder.encode(userId) },
    await tokenKey(secret),
    encoder.encode(token),
  );
  return `v1.${b64url(iv)}.${b64url(new Uint8Array(sealed))}`;
}

/** The refresh token, or null when it does not open (another secret, another account, tampered). */
export async function unseal(
  secret: string,
  userId: string,
  sealed: string,
): Promise<string | null> {
  const parts = sealed.split('.');
  if (parts.length !== 3 || parts[0] !== 'v1') return null;
  try {
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: fromB64url(parts[1] ?? ''), additionalData: encoder.encode(userId) },
      await tokenKey(secret),
      fromB64url(parts[2] ?? ''),
    );
    return decoder.decode(plain);
  } catch {
    return null;
  }
}

// Calls to Google -----------------------------------------------------------------------------

async function postForm(url: string, form: Record<string, string>): Promise<Response> {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(form).toString(),
  });
}

async function readJson(response: Response): Promise<Record<string, unknown> | null> {
  try {
    const value: unknown = await response.json();
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** A Google account: its email, and its own id (the ID token's sub), which never changes. */
interface GoogleAccount {
  readonly email: string;
  readonly sub: string | null;
}

/**
 * The account in an ID token straight from Google's token endpoint over TLS (OIDC 3.1.3.7): its
 * verified email and its sub.
 */
function accountOfIdToken(idToken: unknown): GoogleAccount | null {
  if (typeof idToken !== 'string') return null;
  const payload = idToken.split('.')[1];
  if (payload === undefined) return null;
  try {
    const claims = JSON.parse(decoder.decode(fromB64url(payload))) as Record<string, unknown>;
    const email = claims.email;
    if (claims.email_verified !== true || typeof email !== 'string' || !EMAIL.test(email))
      return null;
    const sub = typeof claims.sub === 'string' && SUB.test(claims.sub) ? claims.sub : null;
    return { email, sub };
  } catch {
    return null;
  }
}

interface LinkRow {
  google_email: string;
  google_sub: string | null;
  scopes: string;
  refresh_token: string;
  connected_at: number;
  used_at: number | null;
}

function accountOf(link: LinkRow): GoogleAccount {
  return { email: link.google_email, sub: link.google_sub };
}

async function readLink(env: Env, userId: string): Promise<LinkRow | null> {
  return env.DB.prepare(
    `SELECT google_email, google_sub, scopes, refresh_token, connected_at, used_at
     FROM google_links WHERE user_id = ?1`,
  )
    .bind(userId)
    .first<LinkRow>();
}

/**
 * The links to one Google account (?1 its email, ?2 its sub): by sub where both sides have one,
 * else by email (a row kept before the sub was).
 */
const SAME_GOOGLE = `((?2 IS NOT NULL AND google_sub IS NOT NULL AND google_sub = ?2)
  OR ((?2 IS NULL OR google_sub IS NULL) AND google_email = ?1 COLLATE NOCASE))`;

function sameGoogle(a: GoogleAccount, b: GoogleAccount): boolean {
  return a.sub !== null && b.sub !== null
    ? a.sub === b.sub
    : a.email.toLowerCase() === b.email.toLowerCase();
}

/**
 * ONE GRANT PER GOOGLE ACCOUNT: Google's revoke ends the whole grant a Google account gave this
 * client, every refresh token of it, so every Snowlight account linked to that Google account at
 * once. Whether another Snowlight account than `userId` holds a link to the same Google account
 * (its sub: a renamed address is the same account, a reused one is not).
 */
async function heldElsewhere(env: Env, userId: string, who: GoogleAccount): Promise<boolean> {
  const row = await env.DB.prepare(
    `SELECT 1 AS held FROM google_links WHERE ${SAME_GOOGLE} AND user_id <> ?3 LIMIT 1`,
  )
    .bind(who.email, who.sub, userId)
    .first<{ held: number }>();
  return row !== null;
}

/**
 * Ends a grant that must not stay (it can read Gmail): revoked at Google, and every link to that
 * Google account deleted, on any Snowlight account, since none of their tokens works after it.
 * So no page reads as connected on a grant that is gone.
 */
async function endGrant(env: Env, who: GoogleAccount, token: string): Promise<void> {
  await revokeToken(token);
  await env.DB.prepare(`DELETE FROM google_links WHERE ${SAME_GOOGLE}`)
    .bind(who.email, who.sub)
    .run();
}

/**
 * A fresh access token for the account's link. A token Google no longer takes (the person
 * removed the access in their Google account) deletes the link: Google reads as disconnected.
 * Only that token's link (SAFE-R4-B1): a connect that finished while Google was asked has put a
 * new token in the row, and that link stays, as does any connect still waiting for its finish.
 */
async function accessToken(env: Env, userId: string, link: LinkRow, now: number): Promise<string> {
  const { id, secret } = requireConfigured(env);
  const refresh = await unseal(secret, userId, link.refresh_token);
  if (refresh === null) {
    await dropToken(env, userId, link.refresh_token);
    throw new HttpError(409, 'google_revoked');
  }
  const response = await postForm(GOOGLE.token, {
    client_id: id,
    client_secret: secret,
    refresh_token: refresh,
    grant_type: 'refresh_token',
  });
  const body = await readJson(response);
  if (response.status === 400 && body?.error === 'invalid_grant') {
    await dropToken(env, userId, link.refresh_token);
    throw new HttpError(409, 'google_revoked');
  }
  const token = body?.access_token;
  if (!response.ok || typeof token !== 'string' || token.length === 0)
    throw new HttpError(502, 'google_failed');
  // A refresh that answers with a scope never asked for (a Gmail read grant that reached the
  // link) is never used: the grant is revoked and the link deleted, so the page says what is so.
  if (extraScopes(body?.scope).length > 0) {
    await endGrant(env, accountOf(link), refresh);
    throw new HttpError(409, 'google_revoked');
  }
  await env.DB.prepare(
    'UPDATE google_links SET used_at = ?2 WHERE user_id = ?1 AND refresh_token = ?3',
  )
    .bind(userId, now, link.refresh_token)
    .run();
  return token;
}

/**
 * The scopes in a token answer that this Worker never asks for. Above all gmail.readonly or
 * mail.google.com (D19 GOOGLE RULE: a token that can read Gmail is never kept here). Google
 * names the email scope "userinfo.email" in its answers.
 */
export function extraScopes(scope: unknown): string[] {
  if (typeof scope !== 'string') return [];
  const allowed = new Set<string>([...SCOPES, 'https://www.googleapis.com/auth/userinfo.email']);
  return scope.split(/\s+/).filter((one) => one !== '' && !allowed.has(one));
}

/** Asks Google to revoke a token this Worker will not keep; a failure there changes nothing. */
async function revokeToken(token: string): Promise<void> {
  try {
    await postForm(GOOGLE.revoke, { token });
  } catch {
    // Nothing of it is kept here either way.
  }
}

/** Deletes the account's link only while it still holds this (sealed) token. */
async function dropToken(env: Env, userId: string, sealed: string): Promise<void> {
  await env.DB.prepare('DELETE FROM google_links WHERE user_id = ?1 AND refresh_token = ?2')
    .bind(userId, sealed)
    .run();
}

async function dropLink(env: Env, userId: string): Promise<void> {
  await env.DB.batch(eraseGoogle(env, userId));
}

/**
 * Asks Google to revoke the account's refresh token, before its link is deleted (disconnect,
 * another Google account, account deletion); a failure there changes nothing here. Not while
 * another Snowlight account holds a link to the same Google account: the revoke would end that
 * link too, which would then read as connected with nothing working. The token is deleted here
 * either way.
 */
export async function revokeAt(env: Env, userId: string): Promise<void> {
  if (!configured(env)) return;
  const link = await readLink(env, userId).catch(() => null);
  if (link === null) return;
  if (await heldElsewhere(env, userId, accountOf(link)).catch(() => true)) return;
  const refresh = await unseal((env.GOOGLE_CLIENT_SECRET ?? '').trim(), userId, link.refresh_token);
  if (refresh === null) return;
  try {
    await postForm(GOOGLE.revoke, { token: refresh });
  } catch {
    // Revoking is a courtesy: the token is deleted here either way.
  }
}

/** The statements that remove what Google left for an account. */
export function eraseGoogle(env: Env, userId: string): D1PreparedStatement[] {
  return [
    env.DB.prepare('DELETE FROM google_links WHERE user_id = ?1').bind(userId),
    env.DB.prepare('DELETE FROM google_states WHERE user_id = ?1').bind(userId),
  ];
}

/** The daily sweep's part: connects that were never finished. */
export function sweepGoogle(env: Env, now: number): D1PreparedStatement {
  return env.DB.prepare('DELETE FROM google_states WHERE expires_at <= ?1').bind(now);
}

// Routes --------------------------------------------------------------------------------------

/** GET /v1/me/google: whether this account is connected, as whom, and what it may do. */
export async function getGoogle(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  if (!configured(env)) return json(200, { configured: false, connected: false });
  let link = await readLink(env, user.id);
  if (link === null) return json(200, { configured: true, connected: false });
  // A link near or past Testing mode's 7 days, not used lately: asked of Google, so the page
  // never says connected (and email on) on a token that is gone. A token Google no longer takes
  // deletes the link; Google being down leaves it as it reads. Network wait, not CPU.
  if (
    now - link.connected_at > CHECK_AFTER_MS &&
    (link.used_at === null || now - link.used_at > RECHECK_MS)
  ) {
    try {
      await accessToken(env, user.id, link, now);
    } catch {
      // Google being down leaves the link as it reads; a dead token's link is gone (below).
    }
    // Answered from the row as it is now, never the one read before Google answered: a connect
    // that finished meanwhile is the state (SAFE-R4-B1), never the old row's day.
    link = await readLink(env, user.id);
    if (link === null) return json(200, { configured: true, connected: false });
  }
  const scopes = link.scopes.split(' ');
  return json(200, {
    configured: true,
    connected: true,
    email: link.google_email,
    calendar: scopes.includes(SCOPE_CALENDAR),
    send: scopes.includes(SCOPE_SEND),
    // When it was connected (ms): a Google client in Testing mode ends its tokens after 7 days.
    since: link.connected_at,
  });
}

/** POST /v1/me/google/start: Google's sign-in address for this account, with a fresh state. */
export async function startGoogle(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const { id } = requireConfigured(env);
  const origin = allowedOrigin(env, request.headers.get('Origin'));
  if (origin === null) throw new HttpError(400, 'origin');
  // The site's base path ("/", or "/repo/" for a GitHub Pages preview): /google.html sits there.
  const body = await readBody(request);
  const base = body.base === undefined ? '/' : body.base;
  if (typeof base !== 'string' || !BASE.test(base)) throw new HttpError(400, 'bad_base');
  const back = `${origin}${base.replace(/\/$/, '')}`;
  await env.DB.prepare('DELETE FROM google_states WHERE user_id = ?1 AND expires_at <= ?2')
    .bind(user.id, now)
    .run();
  const open = await env.DB.prepare('SELECT COUNT(*) AS n FROM google_states WHERE user_id = ?1')
    .bind(user.id)
    .first<{ n: number }>();
  if ((open?.n ?? 0) >= MAX_STATES) throw new HttpError(429, 'too_many');
  const state = b64url(randomBytes(32));
  const verifier = b64url(randomBytes(32));
  const challenge = b64url(await sha256(verifier));
  await env.DB.prepare(
    `INSERT INTO google_states (state_hash, user_id, verifier, return_origin, expires_at)
     VALUES (?1, ?2, ?3, ?4, ?5)`,
  )
    .bind(b64url(await sha256(state)), user.id, verifier, back, now + STATE_MS)
    .run();
  const url = new URL(GOOGLE.auth);
  url.search = new URLSearchParams({
    client_id: id,
    redirect_uri: `${back}${RETURN_PATH}`,
    response_type: 'code',
    scope: SCOPES.join(' '),
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    access_type: 'offline',
    prompt: 'consent',
    // No include_granted_scopes: the token asks for these scopes only, never a grant the person
    // gave the Gmail demo (D19 GOOGLE RULE).
  }).toString();
  return json(200, { url: url.href });
}

/** POST /v1/me/google/finish {code, state}: keeps the link, for the account that started it. */
export async function finishGoogle(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const { id, secret } = requireConfigured(env);
  const body = await readBody(request);
  const code = body.code;
  const state = body.state;
  if (typeof code !== 'string' || code.length === 0 || code.length > 512 || /\s/.test(code))
    throw new HttpError(400, 'bad_state');
  if (typeof state !== 'string' || !STATE.test(state)) throw new HttpError(400, 'bad_state');
  // Used once, whoever sends it: a state another account started is gone with this answer too.
  const row = await env.DB.prepare(
    `DELETE FROM google_states WHERE state_hash = ?1
     RETURNING user_id, verifier, return_origin, expires_at`,
  )
    .bind(b64url(await sha256(state)))
    .first<{ user_id: string; verifier: string; return_origin: string; expires_at: number }>();
  if (row === null || row.expires_at <= now || !(await secretEqual(row.user_id, user.id)))
    throw new HttpError(400, 'bad_state');
  const response = await postForm(GOOGLE.token, {
    code,
    client_id: id,
    client_secret: secret,
    redirect_uri: `${row.return_origin}${RETURN_PATH}`,
    grant_type: 'authorization_code',
    code_verifier: row.verifier,
  });
  const tokens = await readJson(response);
  if (!response.ok || tokens === null) throw new HttpError(502, 'google_refused');
  const refresh = tokens.refresh_token;
  const who = accountOfIdToken(tokens.id_token);
  const email = who?.email ?? null;
  const scopes = typeof tokens.scope === 'string' ? tokens.scope : '';
  if (
    typeof refresh !== 'string' ||
    refresh.length === 0 ||
    refresh.length > 1024 ||
    who === null ||
    email === null
  )
    throw new HttpError(502, 'google_refused');
  const before = await readLink(env, user.id);
  // A token that covers more than this Worker asked for (gmail.readonly above all) is revoked at
  // Google and nothing of it is kept. The revoke ends the Google account's whole grant, so a link
  // to the same Google account (this account's own, on a reconnect, or another's) ends with it:
  // deleted too, so Google reads as disconnected, never connected on a dead grant. A link to
  // another Google account is another grant and stays.
  if (extraScopes(scopes).length > 0) {
    await endGrant(env, who, refresh);
    throw new HttpError(502, 'google_scopes');
  }
  // Connecting another Google account: the old account's grant is revoked first, so no grant is
  // left live at Google that nothing here holds. The same account keeps its grant (revoking it
  // would also end the one just given).
  if (before !== null && !sameGoogle(accountOf(before), who)) await revokeAt(env, user.id);
  const granted = scopes
    .split(' ')
    .filter((scope) => (SCOPES as readonly string[]).includes(scope));
  await env.DB.prepare(
    `INSERT INTO google_links (user_id, google_email, google_sub, scopes, refresh_token, connected_at)
     VALUES (?1, ?2, ?6, ?3, ?4, ?5)
     ON CONFLICT (user_id) DO UPDATE SET
       google_email = ?2, google_sub = ?6, scopes = ?3, refresh_token = ?4, connected_at = ?5,
       used_at = NULL`,
  )
    .bind(user.id, email, granted.join(' '), await seal(secret, user.id, refresh), now, who.sub)
    .run();
  return json(200, {
    configured: true,
    connected: true,
    email,
    calendar: granted.includes(SCOPE_CALENDAR),
    send: granted.includes(SCOPE_SEND),
    since: now,
  });
}

/** DELETE /v1/me/google: revokes at Google and deletes the link here. */
export async function disconnectGoogle(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  await revokeAt(env, user.id);
  await dropLink(env, user.id);
  return json(200, { connected: false });
}

/** A calendar event, cut to what the page reads to find a flight in it. */
export interface CalendarEvent {
  summary: string;
  location: string;
  description: string;
  start: string | null;
  start_day: string | null;
  zone: string | null;
  end: string | null;
}

const FLIGHTISH = /\b(?:[A-Z][A-Z0-9]|[0-9][A-Z])\s?\d{1,4}\b|\bflight\b/i;

function cut(value: unknown, max: number): string {
  return typeof value === 'string' ? value.slice(0, max) : '';
}

function timeOf(value: unknown): { at: string | null; day: string | null; zone: string | null } {
  if (typeof value !== 'object' || value === null) return { at: null, day: null, zone: null };
  const v = value as Record<string, unknown>;
  return {
    at: typeof v.dateTime === 'string' ? v.dateTime.slice(0, 40) : null,
    day: typeof v.date === 'string' ? v.date.slice(0, 10) : null,
    zone: typeof v.timeZone === 'string' ? v.timeZone.slice(0, 64) : null,
  };
}

/**
 * POST /v1/me/google/calendar: the next 60 days of the person's own calendar events that read
 * like a flight, cut short. Nothing is kept: the page matches them to the usual flights and the
 * person confirms each one, which saves only the trip's fields, as typing them does.
 */
export async function importCalendar(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  requireConfigured(env);
  const [count] = await hits(env, [
    hit(env, await bucket('google-calendar', user.id), 60 * 60_000, now),
  ]);
  if ((count ?? 0) > CALENDAR_PER_HOUR) throw new HttpError(429, 'too_many');
  const link = await readLink(env, user.id);
  if (link === null || !link.scopes.split(' ').includes(SCOPE_CALENDAR))
    throw new HttpError(404, 'not_connected');
  const token = await accessToken(env, user.id, link, now);
  const url = new URL(GOOGLE.events);
  url.search = new URLSearchParams({
    timeMin: new Date(now).toISOString(),
    timeMax: new Date(now + CALENDAR_DAYS * 86_400_000).toISOString(),
    singleEvents: 'true',
    orderBy: 'startTime',
    maxResults: String(MAX_EVENTS),
    fields: 'items(summary,location,description,start,end)',
  }).toString();
  const response = await fetch(url.href, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new HttpError(502, 'google_failed');
  const body = await readJson(response);
  const items = Array.isArray(body?.items) ? (body.items as unknown[]).slice(0, MAX_EVENTS) : [];
  const events: CalendarEvent[] = [];
  for (const item of items) {
    if (typeof item !== 'object' || item === null) continue;
    const e = item as Record<string, unknown>;
    const summary = cut(e.summary, 200);
    const location = cut(e.location, 200);
    const description = cut(e.description, 600);
    if (!FLIGHTISH.test(`${summary} ${location} ${description}`)) continue;
    const start = timeOf(e.start);
    events.push({
      summary,
      location,
      description,
      start: start.at,
      start_day: start.day,
      zone: start.zone,
      end: timeOf(e.end).at,
    });
  }
  return json(200, { events });
}

/**
 * Words one made-up alert's email at startup (index.ts), which has its own time limit, so the
 * first email a request sends does not pay for compiling the words or Intl's first formatter.
 */
export function prepareEmail(): void {
  const facts = readAlert({
    v: 1,
    kind: 'flight',
    alert: 'chance',
    trip: '0'.repeat(32),
    carrier: 'WN',
    number: 1,
    from: 'MCI',
    to: 'LAX',
    day: '2026-01-05',
    leaves: 600,
    cancel: 30,
    late: 10,
    level: 'cancel',
    why: 0,
    faa: null,
    waiver: null,
    backups: [],
    ticket: 'unsure',
  });
  if (facts !== null) alertEmail(facts, 'https://snowlightmap.com/');
}

// The alert email (sent for the Actions sender) ------------------------------------------------

/** The key the sender wrote (settings MAIL_KEY: "<sha256 hex>:<end ms>") matches and still lasts. */
async function senderKeyOk(env: Env, request: Request, now: number): Promise<boolean> {
  const header = request.headers.get('Authorization') ?? '';
  const key = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(header)?.[1];
  if (key === undefined) return false;
  const row = await env.DB.prepare('SELECT value FROM settings WHERE name = ?1')
    .bind(MAIL_KEY)
    .first<{ value: string }>();
  const match = row === null ? null : /^([0-9a-f]{64}):(\d{1,16})$/.exec(row.value);
  if (match === null || Number(match[2]) <= now) return false;
  const digest = [...(await sha256(key))].map((b) => b.toString(16).padStart(2, '0')).join('');
  return secretEqual(digest, match[1] ?? '');
}

function wrap76(text: string): string {
  return text.replace(/.{1,76}/g, '$&\r\n');
}

function base64Utf8(text: string): string {
  let binary = '';
  for (const byte of encoder.encode(text)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** The message as Gmail's API takes it: RFC 2822, base64url. Exported for its tests. */
export function mimeOf(to: string, subject: string, text: string, html: string): string {
  if (!EMAIL.test(to)) throw new HttpError(400, 'bad_mail');
  const boundary = `snowlight-${b64url(randomBytes(12))}`;
  const message = [
    `From: Snowlight <${to}>`,
    `To: ${to}`,
    `Subject: =?UTF-8?B?${base64Utf8(subject.replace(/[\r\n]+/g, ' '))}?=`,
    'MIME-Version: 1.0',
    `Content-Type: multipart/alternative; boundary="${boundary}"`,
    '',
    `--${boundary}`,
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: base64',
    '',
    wrap76(base64Utf8(text)),
    `--${boundary}`,
    'Content-Type: text/html; charset=UTF-8',
    'Content-Transfer-Encoding: base64',
    '',
    wrap76(base64Utf8(html)),
    `--${boundary}--`,
    '',
  ].join('\r\n');
  return b64url(encoder.encode(message));
}

/** The site's own address for a trip, from the first allowed origin. */
function tripLink(env: Env, trip: string): string {
  const origin = (env.ALLOWED_ORIGINS ?? '').split(',')[0]?.trim() || 'https://snowlightmap.com';
  const url = new URL('/', origin);
  url.searchParams.set('mode', 'flights');
  url.searchParams.set('page', 'trips');
  url.searchParams.set('trip', trip);
  return url.href;
}

/**
 * POST /v1/internal/flights/mail {user_id, alert}: the sender's one call per email. The sender
 * proves itself with a key whose SHA-256 it wrote in the settings table over the Cloudflare API
 * a moment before (no secret of its own); the Worker reads the alert's facts strictly, words them
 * (copy-trips.ts alertEmail) and sends them from the account's own Gmail to itself.
 */
export async function sendAlertMail(env: Env, request: Request, now: number): Promise<Response> {
  if (!(await senderKeyOk(env, request, now))) throw new HttpError(401, 'sender');
  requireConfigured(env);
  const body = await readBody(request);
  const userId =
    typeof body.user_id === 'string' && USER_ID.test(body.user_id) ? body.user_id : null;
  const facts = readAlert(body.alert);
  if (userId === null || facts === null) throw new HttpError(400, 'bad_mail');
  const link = await readLink(env, userId);
  if (link === null || !link.scopes.split(' ').includes(SCOPE_SEND))
    throw new HttpError(404, 'not_connected');
  const token = await accessToken(env, userId, link, now);
  // Backups are said only while they can still be caught (the sender names ones 2 hours on).
  const mail = alertEmail(facts, tripLink(env, facts.trip), Math.floor(now / 1000));
  const response = await fetch(GOOGLE.send, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw: mimeOf(link.google_email, mail.subject, mail.text, mail.html) }),
  });
  if (!response.ok) throw new HttpError(502, 'google_failed');
  return json(200, { sent: true });
}

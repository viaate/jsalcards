/** Key hashes, sessions and rate limits. */

import { HttpError, type Env } from './http';
import {
  b64url,
  bytesEqual,
  concat,
  fromB64url,
  randomBytes,
  randomHex,
  secretEqual,
  sha256,
} from './util';

export const SESSION_MS = 30 * 24 * 60 * 60 * 1000;
/** A session's expiry slides forward at most once an hour, so reads stay reads. */
const REFRESH_MS = 60 * 60 * 1000;
export const DAY_MS = 24 * 60 * 60 * 1000;

export interface UserRow {
  id: string;
  login: string;
  email: string | null;
  name: string;
  role: 'user' | 'admin';
  salt: string | null;
  key_hash: string | null;
  schools: string;
  disabled: number;
  created_at: number;
  last_login_at: number | null;
  /** Migration 0003: lowercase a-z 0-9 _, unique; null until the account picks one. */
  username: string | null;
  /** #0001-#9999 in sign-up order; null after #9999. */
  join_number: number | null;
  /** 1 once this Worker has given the account its number or found none left (0: made by the old Worker). */
  numbered: number;
  /** The admin renamed it: the next sign-in asks for a new one. */
  rename_required: number;
  /** The client salt of the email key (base64url); null for a v1 key salted by the email. */
  email_salt: string | null;
  /** The client salt of the username key; null while the account has none. */
  name_salt: string | null;
  name_key_salt: string | null;
  name_key_hash: string | null;
}

export interface SavedSchool {
  id: string;
  name: string;
}

export interface PublicUser {
  id: string;
  name: string;
  email: string | null;
  role: 'user' | 'admin';
  schools: SavedSchool[];
  created_at: string;
  username: string | null;
  join_number: number | null;
  /** No username yet, or the admin changed it: the account must pick one before anything else. */
  username_required: boolean;
  /** The changed username's reason, for the pick view's message. */
  renamed: boolean;
  /** The account's keys predate usernames: the browser derives fresh ones at its next login. */
  needs_rekey: boolean;
}

export function schoolsOf(row: Pick<UserRow, 'schools'>): SavedSchool[] {
  try {
    const parsed: unknown = JSON.parse(row.schools);
    return Array.isArray(parsed) ? (parsed as SavedSchool[]) : [];
  } catch {
    return [];
  }
}

export function publicUser(row: UserRow): PublicUser {
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    role: row.role,
    schools: schoolsOf(row),
    created_at: new Date(row.created_at).toISOString(),
    username: row.username,
    join_number: row.join_number,
    username_required: row.role !== 'admin' && (row.username === null || row.rename_required !== 0),
    renamed: row.role !== 'admin' && row.rename_required !== 0,
    needs_rekey: row.role !== 'admin' && (row.email_salt === null || row.name_salt === null),
  };
}

/** A fresh salt and the stored hash for a key: SHA-256(salt || key bytes). */
export async function hashKey(key: string): Promise<{ salt: string; key_hash: string }> {
  const salt = randomBytes(16);
  const digest = await sha256(concat(salt, fromB64url(key)));
  return { salt: b64url(salt), key_hash: b64url(digest) };
}

export async function keyMatches(
  row: Pick<UserRow, 'salt' | 'key_hash'>,
  key: string,
): Promise<boolean> {
  return hashMatches(row.salt, row.key_hash, key);
}

/** The username key: the same SHA-256(salt || key) check against its own salt and hash. */
export async function nameKeyMatches(
  row: Pick<UserRow, 'name_key_salt' | 'name_key_hash'>,
  key: string,
): Promise<boolean> {
  return hashMatches(row.name_key_salt, row.name_key_hash, key);
}

async function hashMatches(
  salt: string | null,
  hash: string | null,
  key: string,
): Promise<boolean> {
  if (salt === null || hash === null) return false;
  const digest = await sha256(concat(fromB64url(salt), fromB64url(key)));
  return bytesEqual(digest, fromB64url(hash));
}

export function newUserId(): string {
  return randomHex(16);
}

export async function tokenHash(token: string): Promise<string> {
  return b64url(await sha256(token));
}

export async function createSession(env: Env, userId: string, now: number): Promise<string> {
  const token = b64url(randomBytes(32));
  await env.DB.prepare(
    'INSERT INTO sessions (token_hash, user_id, created_at, expires_at, refreshed_at) VALUES (?1, ?2, ?3, ?4, ?3)',
  )
    .bind(await tokenHash(token), userId, now, now + SESSION_MS)
    .run();
  return token;
}

export interface Session {
  tokenHash: string;
  user: UserRow;
}

function bearer(request: Request): string | null {
  const header = request.headers.get('Authorization') ?? '';
  const match = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(header);
  return match ? match[1]! : null;
}

/**
 * The signed-in user, read fresh from D1 on every request (so a role change,
 * disable or delete takes effect at once), or a 401.
 */
export async function requireSession(env: Env, request: Request, now: number): Promise<Session> {
  const token = bearer(request);
  if (token === null) throw new HttpError(401, 'signed_out');
  const hash = await tokenHash(token);
  const row = await env.DB.prepare(
    `SELECT s.expires_at AS s_expires, s.refreshed_at AS s_refreshed, u.*
       FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ?1`,
  )
    .bind(hash)
    .first<UserRow & { s_expires: number; s_refreshed: number }>();
  if (row === null || row.s_expires <= now || row.disabled !== 0) {
    if (row !== null)
      await env.DB.prepare('DELETE FROM sessions WHERE token_hash = ?1').bind(hash).run();
    throw new HttpError(401, 'signed_out');
  }
  if (now - row.s_refreshed >= REFRESH_MS) {
    await env.DB.prepare(
      'UPDATE sessions SET expires_at = ?2, refreshed_at = ?3 WHERE token_hash = ?1',
    )
      .bind(hash, now + SESSION_MS, now)
      .run();
  }
  if (row.role === 'admin') {
    const stamp = await adminStamp(env);
    if (stamp === null || row.key_hash === null || !(await secretEqual(stamp, row.key_hash))) {
      await revokeSessions(env, row.id);
      throw new HttpError(401, 'signed_out');
    }
  }
  const { s_expires: _e, s_refreshed: _r, ...user } = row;
  return { tokenHash: hash, user };
}

/**
 * What the admin's row keeps of the ADMIN_KEY its sessions were made with: a
 * SHA-256 of it, never the key. A new admin password (a new ADMIN_KEY), or
 * none, ends every admin session at its next request.
 */
export async function adminStamp(env: Env): Promise<string | null> {
  const key = env.ADMIN_KEY ?? '';
  return /^[A-Za-z0-9_-]{43}$/.test(key) ? b64url(await sha256(`snowlight-admin|${key}`)) : null;
}

export async function requireAdmin(env: Env, request: Request, now: number): Promise<Session> {
  const session = await requireSession(env, request, now);
  if (session.user.role !== 'admin') throw new HttpError(403, 'forbidden');
  return session;
}

export async function revokeSessions(env: Env, userId: string, except?: string): Promise<void> {
  if (except === undefined) {
    await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?1').bind(userId).run();
  } else {
    await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?1 AND token_hash != ?2')
      .bind(userId, except)
      .run();
  }
}

/** Rate limit buckets never hold an address in the clear. */
export async function bucket(kind: string, value: string): Promise<string> {
  return `${kind}:${b64url((await sha256(`snowlight-rate|${value}`)).subarray(0, 12))}`;
}

/**
 * Counts one attempt in a bucket and returns the count in the current window,
 * in one atomic statement: the count is taken before anything is checked, so
 * requests sent at the same time can never all read a count under the limit.
 */
export function hit(env: Env, name: string, windowMs: number, now: number): D1PreparedStatement {
  return env.DB.prepare(
    `INSERT INTO rate_limits (bucket, count, window_start) VALUES (?1, 1, ?2)
     ON CONFLICT (bucket) DO UPDATE SET
       count = CASE WHEN window_start <= ?3 THEN 1 ELSE count + 1 END,
       window_start = CASE WHEN window_start <= ?3 THEN ?2 ELSE window_start END
     RETURNING count`,
  ).bind(name, now, now - windowMs);
}

/** Runs `hit` statements together and returns each bucket's count, in order. */
export async function hits(env: Env, statements: D1PreparedStatement[]): Promise<number[]> {
  const results = await env.DB.batch<{ count: number }>(statements);
  return results.map((r) => r.results[0]?.count ?? 1);
}

/** Gives back one attempt, for a login that turned out right. */
export async function refund(env: Env, names: string[]): Promise<void> {
  await env.DB.batch(
    names.map((name) =>
      env.DB.prepare('UPDATE rate_limits SET count = MAX(count - 1, 0) WHERE bucket = ?1').bind(
        name,
      ),
    ),
  );
}

/** How long a network the admin logged in from keeps getting past an account lockout. */
export const KNOWN_NETWORK_MS = 30 * DAY_MS;

/** Occasional cleanup of expired sessions, old rate limit windows and long-expired overrides. */
export async function sweep(env: Env, now: number): Promise<void> {
  await env.DB.batch([
    env.DB.prepare('DELETE FROM sessions WHERE expires_at <= ?1').bind(now),
    env.DB.prepare(
      "DELETE FROM rate_limits WHERE window_start <= ?1 AND bucket NOT LIKE 'admin-net:%'",
    ).bind(now - DAY_MS),
    env.DB.prepare(
      "DELETE FROM rate_limits WHERE window_start <= ?1 AND bucket LIKE 'admin-net:%'",
    ).bind(now - KNOWN_NETWORK_MS),
    env.DB.prepare('DELETE FROM overrides WHERE expires_at <= ?1').bind(now - 30 * DAY_MS),
  ]);
}

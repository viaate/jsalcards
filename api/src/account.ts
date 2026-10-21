/** Sign up, log in, log out and the signed-in user's own account. */

import {
  DAY_MS,
  KNOWN_NETWORK_MS,
  adminStamp,
  bucket,
  createSession,
  endSession,
  hashKey,
  hit,
  hits,
  keyMatches,
  nameKeyMatches,
  newUserId,
  publicUser,
  refund,
  requireSession,
  revokeSessions,
  sweep,
  tokenHash,
  type UserRow,
} from './auth';
import { HttpError, clientIp, json, networkOf, readBody, type Env } from './http';
import { RELEASED_HOLD, holdUsername, legacySalt, usableUsername } from './names';
import { eraseNotify } from './notify';
import { secretEqual } from './util';
import * as v from './validate';

const LOGIN_WINDOW = 15 * 60 * 1000;
const LOGIN_LIMIT = 10;
const SIGNUP_WINDOW = 60 * 60 * 1000;
const SIGNUP_LIMIT = 5;
/** Sign-ups per network (an IPv4 /24 or IPv6 /64) per day, so that one host with many addresses cannot use up the join numbers. */
const SIGNUP_NETWORK_WINDOW = DAY_MS;
export const SIGNUP_NETWORK_LIMIT = 20;
/** A network with this many sign-ups in a day is listed in the admin overview. */
export const BUSY_NETWORK = 5;
/** How long the per-network sign-up counts for the admin overview are kept. */
const NETWORK_DAYS_KEPT = 14;

export function adminLogin(env: Env): string {
  return (env.ADMIN_USERNAME ?? 'Olivia').trim().toLowerCase();
}

export async function audit(
  env: Env,
  now: number,
  actor: Pick<UserRow, 'id' | 'name'> | null,
  action: string,
  target: string | null,
  detail: Record<string, unknown> | null = null,
): Promise<void> {
  await env.DB.prepare(
    'INSERT INTO audit (at, actor_id, actor_name, action, target, detail) VALUES (?1, ?2, ?3, ?4, ?5, ?6)',
  )
    .bind(
      now,
      actor?.id ?? null,
      actor?.name ?? null,
      action,
      target,
      detail === null ? null : JSON.stringify(detail),
    )
    .run();
}

/**
 * The keys a sign-up, a password change or a reset sends: the email key with
 * its client salt, and the username key with its own. The email key's salt is
 * always legacySalt(email) (so that asking for an email's salt tells nothing),
 * and email_salt records it: NULL marks an account with no username key yet.
 * A v1 browser's password change sends only the email key: that key is kept,
 * and the account has no username key until its next login.
 */
export interface KeyColumns {
  salt: string;
  key_hash: string;
  email_salt: string | null;
  name_salt: string | null;
  name_key_salt: string | null;
  name_key_hash: string | null;
}

export async function keyColumns(
  body: Record<string, unknown>,
  field: string,
  email: string,
): Promise<KeyColumns> {
  const key = v.key(body[field]);
  if (key === null) throw new HttpError(400, 'bad_key');
  const emailSalt = body.email_salt === undefined ? null : await legacySalt(email);
  if (body.email_salt !== undefined && body.email_salt !== emailSalt)
    throw new HttpError(400, 'bad_key');
  const nameKey = body.name_key === undefined ? null : v.key(body.name_key);
  const nameSalt = body.name_salt === undefined ? null : v.clientSalt(body.name_salt);
  if (
    (body.name_key !== undefined || body.name_salt !== undefined) &&
    (nameKey === null || nameSalt === null)
  )
    throw new HttpError(400, 'bad_key');
  // A username key only comes with an email key of the new kind.
  if (nameKey !== null && emailSalt === null) throw new HttpError(400, 'bad_key');
  const hashed = await hashKey(key);
  const name = nameKey === null ? null : await hashKey(nameKey);
  return {
    salt: hashed.salt,
    key_hash: hashed.key_hash,
    email_salt: emailSalt,
    name_salt: nameSalt,
    name_key_salt: name?.salt ?? null,
    name_key_hash: name?.key_hash ?? null,
  };
}

/** The last join number there is. */
export const LAST_JOIN = 9999;

/**
 * Takes the next join number for account ?1, in one atomic statement that
 * returns it: the counter (the last number handed out) moves up by one only
 * while it is below #9999, never down, and records which account it moved
 * for (holder), so that the statement after it in the same transaction
 * (TAKEN_JOIN) gives that number to this account and to no other. When the
 * counter is at #9999 nothing moves and the account gets none, so a number is
 * never given twice, even after its account is deleted.
 */
const takeJoin = (also = ''): string =>
  `UPDATE counters SET value = value + 1, holder = ?1
    WHERE name = 'join' AND value < ${LAST_JOIN} ${also} RETURNING value`;

/** The number takeJoin took for account ?1 in this transaction, or NULL. */
const TAKEN_JOIN = "(SELECT value FROM counters WHERE name = 'join' AND holder = ?1)";

/**
 * A number for an account the old Worker made (in the seconds between the
 * migration and the new Worker, numbered 0), at its next login or pick, once:
 * whether it gets one or finds none left, it is marked numbered and never
 * asked again, so an account that got none keeps none. Returns the account's
 * join number.
 */
export async function giveJoinNumber(
  env: Env,
  user: Pick<UserRow, 'id' | 'role' | 'join_number' | 'numbered'>,
): Promise<number | null> {
  if (user.role !== 'user' || user.join_number !== null || user.numbered !== 0)
    return user.join_number;
  const results = await env.DB.batch<{ join_number: number | null }>([
    env.DB.prepare(
      takeJoin(
        'AND EXISTS (SELECT 1 FROM users WHERE id = ?1 AND numbered = 0 AND join_number IS NULL)',
      ),
    ).bind(user.id),
    env.DB.prepare(
      `UPDATE users SET join_number = ${TAKEN_JOIN}, numbered = 1 WHERE id = ?1 AND numbered = 0`,
    ).bind(user.id),
    env.DB.prepare('SELECT join_number FROM users WHERE id = ?1').bind(user.id),
  ]);
  return results[2]?.results[0]?.join_number ?? null;
}

/** The UTC day of a time, for the per-network sign-up counts. */
function utcDay(now: number): string {
  return new Date(now).toISOString().slice(0, 10);
}

export async function signup(env: Env, request: Request, now: number): Promise<Response> {
  const body = await readBody(request);
  // Counted before anything is checked, both in one atomic batch (auth.ts
  // hit): per address, and per network, so many addresses of one host share
  // one budget.
  const ip = clientIp(request);
  const network = networkOf(ip);
  const [ipCount, networkCount] = await hits(env, [
    hit(env, await bucket('signup-ip', ip), SIGNUP_WINDOW, now),
    hit(env, await bucket('signup-net', network), SIGNUP_NETWORK_WINDOW, now),
  ]);
  if (ipCount! > SIGNUP_LIMIT || networkCount! > SIGNUP_NETWORK_LIMIT)
    throw new HttpError(429, 'too_many');
  const name = v.name(body.name);
  const email = v.email(body.email);
  if (body.over13 !== true) throw new HttpError(400, 'over13_required');
  if (name === null) throw new HttpError(400, 'bad_name');
  if (email === null || email === adminLogin(env)) throw new HttpError(400, 'bad_email');
  // Every sign-up comes with both keys and a username. A page from before
  // usernames (a v1 page still open) gets this answer and reloads.
  if (
    body.email_salt === undefined ||
    body.name_key === undefined ||
    body.name_salt === undefined ||
    body.username === undefined
  )
    throw new HttpError(400, 'old_version');
  const keys = await keyColumns(body, 'key', email);
  const username = await usableUsername(env, body.username, null, now);
  const existing = await env.DB.prepare('SELECT id FROM users WHERE login = ?1')
    .bind(email)
    .first();
  if (existing !== null) throw new HttpError(409, 'email_taken');
  const id = newUserId();
  try {
    // One transaction: the number, the row, and the network's count for the
    // admin overview. If the row cannot be written, none of it happens.
    const day = utcDay(now);
    await env.DB.batch([
      env.DB.prepare(takeJoin()).bind(id),
      env.DB.prepare(
        `INSERT INTO users (id, login, email, name, role, salt, key_hash, email_salt, name_salt,
                            name_key_salt, name_key_hash, username, join_number, numbered, over13, created_at, last_login_at)
         VALUES (?1, ?2, ?2, ?3, 'user', ?4, ?5, ?6, ?7, ?8, ?9, ?10, ${TAKEN_JOIN}, 1, 1, ?11, ?11)`,
      ).bind(
        id,
        email,
        name,
        keys.salt,
        keys.key_hash,
        keys.email_salt,
        keys.name_salt,
        keys.name_key_salt,
        keys.name_key_hash,
        username,
        now,
      ),
      env.DB.prepare(
        `INSERT INTO signup_networks (network, day, count) VALUES (?1, ?2, 1)
         ON CONFLICT (network, day) DO UPDATE SET count = count + 1`,
      ).bind(network, day),
      env.DB.prepare('DELETE FROM signup_networks WHERE day < ?1').bind(
        utcDay(now - NETWORK_DAYS_KEPT * DAY_MS),
      ),
    ]);
  } catch {
    // The unique indexes: someone took this email or username a moment ago. Nothing was written.
    const again = await env.DB.prepare('SELECT 1 FROM users WHERE login = ?1').bind(email).first();
    throw new HttpError(409, again !== null ? 'email_taken' : 'username_taken');
  }
  const token = await createSession(env, id, now);
  const row = await env.DB.prepare('SELECT * FROM users WHERE id = ?1').bind(id).first<UserRow>();
  return json(201, { token, user: publicUser(row!) });
}

/** The admin's row, made on first login. Its secret lives only in ADMIN_KEY. */
async function adminRow(env: Env, now: number): Promise<UserRow> {
  const login = adminLogin(env);
  const display = (env.ADMIN_USERNAME ?? 'Olivia').trim();
  await env.DB.prepare(
    `INSERT INTO users (id, login, email, name, role, over13, created_at)
     VALUES (?1, ?2, NULL, ?3, 'admin', 1, ?4) ON CONFLICT (login) DO NOTHING`,
  )
    .bind(newUserId(), login, display, now)
    .run();
  // Its sessions hold while ADMIN_KEY is the key they were made with (auth.ts adminStamp).
  // Its username is its login, and it is always #0001.
  await env.DB.prepare(
    `UPDATE users SET key_hash = ?2,
       username = COALESCE(username, (SELECT ?1 WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = ?1))),
       join_number = COALESCE(join_number, (SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM users WHERE join_number = 1)))
     WHERE login = ?1 AND role = 'admin'`,
  )
    .bind(login, await adminStamp(env))
    .run();
  return (await env.DB.prepare('SELECT * FROM users WHERE login = ?1')
    .bind(login)
    .first<UserRow>())!;
}

async function knownNetwork(env: Env, name: string, now: number): Promise<boolean> {
  const row = await env.DB.prepare(
    'SELECT 1 AS known FROM rate_limits WHERE bucket = ?1 AND window_start > ?2',
  )
    .bind(name, now - KNOWN_NETWORK_MS)
    .first();
  return row !== null;
}

export async function login(env: Env, request: Request, now: number): Promise<Response> {
  const body = await readBody(request);
  const raw = typeof body.login === 'string' ? body.login.trim().toLowerCase() : '';
  const key = v.key(body.key);
  if (raw.length === 0 || raw.length > 254 || key === null) throw new HttpError(400, 'bad_login');
  const ip = clientIp(request);
  const ipBucket = await bucket('login-ip', ip);
  const isAdmin = raw === adminLogin(env);
  // The login is an email (it has an @), the admin's name, or a username.
  const byEmail = raw.includes('@');
  const row = isAdmin
    ? null
    : await env.DB.prepare(
        byEmail
          ? "SELECT * FROM users WHERE login = ?1 AND role = 'user'"
          : "SELECT * FROM users WHERE username = ?1 AND role = 'user'",
      )
        .bind(raw)
        .first<UserRow>();
  // One budget per account for its email and another for its username. A
  // username is public, so anyone can use up its budget; the email one, which
  // only the owner knows, stays open.
  const accountBucket = await bucket(
    byEmail || isAdmin ? 'login-account' : 'login-name',
    row?.id ?? raw,
  );
  const networkBucket = isAdmin ? await bucket('admin-net', networkOf(ip)) : null;
  const networkTries = isAdmin ? await bucket('login-net', networkOf(ip)) : null;
  // Every attempt is counted before any key is compared, each count in one
  // atomic step, so attempts sent at the same time cannot get past the limit.
  const [ipCount, accountCount, networkCount] = await hits(env, [
    hit(env, ipBucket, LOGIN_WINDOW, now),
    hit(env, accountBucket, LOGIN_WINDOW, now),
    ...(networkTries !== null ? [hit(env, networkTries, LOGIN_WINDOW, now)] : []),
  ]);
  if (ipCount! > LOGIN_LIMIT) throw new HttpError(429, 'too_many');
  // The admin's name is public, so anyone can fill its account bucket. A
  // network the admin logged in from in the last 30 days still gets through,
  // held to the limit across the whole network, so many addresses in it share
  // one budget; a new network waits out the window.
  if (
    accountCount! > LOGIN_LIMIT &&
    !(
      networkBucket !== null &&
      networkCount! <= LOGIN_LIMIT &&
      (await knownNetwork(env, networkBucket, now))
    )
  )
    throw new HttpError(429, 'too_many');

  let user: UserRow | null = null;
  if (isAdmin) {
    const adminKey = env.ADMIN_KEY ?? '';
    if (v.key(adminKey) !== null && (await secretEqual(key, adminKey)))
      user = await adminRow(env, now);
  } else if (row !== null) {
    if (byEmail ? await keyMatches(row, key) : await nameKeyMatches(row, key)) user = row;
  }
  // One answer for an unknown login, a wrong password and a disabled account.
  if (user === null || user.disabled !== 0) throw new HttpError(401, 'bad_login');
  // A right login does not use up the budget.
  await refund(
    env,
    networkTries !== null ? [ipBucket, accountBucket, networkTries] : [ipBucket, accountBucket],
  );
  if (networkBucket !== null)
    await env.DB.prepare(
      `INSERT INTO rate_limits (bucket, count, window_start) VALUES (?1, 0, ?2)
       ON CONFLICT (bucket) DO UPDATE SET window_start = ?2`,
    )
      .bind(networkBucket, now)
      .run();
  await env.DB.prepare('UPDATE users SET last_login_at = ?2 WHERE id = ?1')
    .bind(user.id, now)
    .run();
  const join_number = await giveJoinNumber(env, user);
  const token = await createSession(env, user.id, now);
  if (user.role === 'admin') await audit(env, now, user, 'admin_login', null);
  if (Math.random() < 0.05) await sweep(env, now);
  return json(200, { token, user: publicUser({ ...user, last_login_at: now, join_number }) });
}

export async function logout(env: Env, request: Request, now: number): Promise<Response> {
  const session = await requireSession(env, request, now);
  await endSession(env, session.tokenHash);
  return json(200, { ok: true });
}

export async function me(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  return json(200, { user: publicUser(user) });
}

/**
 * Name, email and password changes. A new email or password needs the current
 * key (the email key) and comes with fresh keys from the browser: the email key
 * with its client salt and the username key with its own (keyColumns). A
 * change without a username key (a v1 browser) drops the old one, so an old
 * password never keeps working by username. Any key change signs out every
 * other session and hands this one a new token. The same call with the same
 * password gives a v1 account its username key at its first login.
 */
export async function updateMe(env: Env, request: Request, now: number): Promise<Response> {
  const session = await requireSession(env, request, now);
  const { user } = session;
  const body = await readBody(request);
  const sets: string[] = [];
  const values: unknown[] = [];
  if (body.name !== undefined) {
    const name = v.name(body.name);
    if (name === null) throw new HttpError(400, 'bad_name');
    sets.push('name');
    values.push(name);
  }
  const wantsEmail = body.email !== undefined;
  const wantsKey = body.new_key !== undefined;
  if (wantsEmail || wantsKey) {
    if (user.role === 'admin') throw new HttpError(400, 'admin_managed');
    const current = v.key(body.current_key);
    if (current === null || !(await keyMatches(user, current)))
      throw new HttpError(403, 'wrong_password');
    // A new email always comes with a new key (an email key is salted by the email).
    const email = wantsEmail ? v.email(body.email) : user.email;
    if (email === null || email === adminLogin(env)) throw new HttpError(400, 'bad_email');
    const keys = await keyColumns(body, 'new_key', email);
    if (wantsEmail) {
      if (email !== user.email) {
        const taken = await env.DB.prepare('SELECT id FROM users WHERE login = ?1')
          .bind(email)
          .first();
        if (taken !== null) throw new HttpError(409, 'email_taken');
      }
      sets.push('email', 'login');
      values.push(email, email);
    }
    for (const column of [
      'salt',
      'key_hash',
      'email_salt',
      'name_salt',
      'name_key_salt',
      'name_key_hash',
    ] as const) {
      sets.push(column);
      values.push(keys[column]);
    }
  }
  if (sets.length === 0) throw new HttpError(400, 'nothing_to_change');
  const assignments = sets.map((column, i) => `${column} = ?${i + 2}`).join(', ');
  await env.DB.prepare(`UPDATE users SET ${assignments} WHERE id = ?1`)
    .bind(user.id, ...values)
    .run();
  let token: string | undefined;
  if (wantsEmail || wantsKey) {
    // Every other sign-in ends, and with it every other browser's notifications; this
    // browser's carry over to the new token.
    token = await createSession(env, user.id, now);
    const fresh = await tokenHash(token);
    await env.DB.prepare('UPDATE push_subscriptions SET session_hash = ?2 WHERE session_hash = ?1')
      .bind(session.tokenHash, fresh)
      .run();
    await revokeSessions(env, user.id, fresh);
  }
  const row = await env.DB.prepare('SELECT * FROM users WHERE id = ?1')
    .bind(user.id)
    .first<UserRow>();
  return json(
    200,
    token === undefined ? { user: publicUser(row!) } : { token, user: publicUser(row!) },
  );
}

/**
 * Removes an account and everything that names it: its row (name, email,
 * schools, keys), its sessions, its push subscriptions, notification settings
 * and sent log, its login rate counts, and every admin log
 * entry's mention of its email (v1 entries named accounts by email; they now
 * name its id). The admin log keeps only the id, join number and username.
 * The username it picked is held for 30 days (by a hash of its skeleton,
 * linked to nothing), so that nobody can take it at once and pass for it.
 */
export async function eraseAccount(env: Env, user: UserRow, now: number): Promise<void> {
  const buckets = await Promise.all(
    [user.id, user.email, user.username, user.login]
      .filter((value): value is string => value !== null)
      .flatMap((value) => [bucket('login-account', value), bucket('login-name', value)]),
  );
  await env.DB.batch([
    env.DB.prepare('DELETE FROM sessions WHERE user_id = ?1').bind(user.id),
    ...eraseNotify(env, user.id),
    env.DB.prepare('DELETE FROM users WHERE id = ?1').bind(user.id),
    ...(user.email !== null
      ? [env.DB.prepare('UPDATE audit SET target = ?1 WHERE target = ?2').bind(user.id, user.email)]
      : []),
    ...buckets.map((name) =>
      env.DB.prepare('DELETE FROM rate_limits WHERE bucket = ?1').bind(name),
    ),
    env.DB.prepare('DELETE FROM held_usernames WHERE until IS NOT NULL AND until <= ?1').bind(now),
    ...(user.username !== null && user.rename_required === 0 && user.role === 'user'
      ? await holdUsername(env, user.username, now + RELEASED_HOLD)
      : []),
  ]);
}

export async function deleteMe(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  if (user.role === 'admin') throw new HttpError(400, 'admin_managed');
  const key = v.key(body.key);
  if (key === null || !(await keyMatches(user, key))) throw new HttpError(403, 'wrong_password');
  await eraseAccount(env, user, now);
  return json(200, { ok: true });
}

export async function putSchools(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  if (!Array.isArray(body.schools) || body.schools.length > v.MAX_SCHOOLS)
    throw new HttpError(400, 'bad_schools');
  const schools: { id: string; name: string }[] = [];
  for (const item of body.schools as unknown[]) {
    if (!v.isRecord(item)) throw new HttpError(400, 'bad_schools');
    const id = v.schoolId(item.id);
    const name = v.plain(item.name, 1, 120);
    if (id === null || name === null) throw new HttpError(400, 'bad_schools');
    if (!schools.some((s) => s.id === id)) schools.push({ id, name });
  }
  await env.DB.prepare('UPDATE users SET schools = ?2 WHERE id = ?1')
    .bind(user.id, JSON.stringify(schools))
    .run();
  return json(200, { user: publicUser({ ...user, schools: JSON.stringify(schools) }) });
}

export { DAY_MS };

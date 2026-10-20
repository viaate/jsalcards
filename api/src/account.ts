/** Sign up, log in, log out and the signed-in user's own account. */

import {
  DAY_MS,
  KNOWN_NETWORK_MS,
  adminStamp,
  bucket,
  createSession,
  hashKey,
  hit,
  hits,
  keyMatches,
  newUserId,
  publicUser,
  refund,
  requireSession,
  revokeSessions,
  sweep,
  type UserRow,
} from './auth';
import { HttpError, clientIp, json, networkOf, readBody, type Env } from './http';
import { secretEqual } from './util';
import * as v from './validate';

const LOGIN_WINDOW = 15 * 60 * 1000;
const LOGIN_LIMIT = 10;
const SIGNUP_WINDOW = 60 * 60 * 1000;
const SIGNUP_LIMIT = 5;

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

export async function signup(env: Env, request: Request, now: number): Promise<Response> {
  const body = await readBody(request);
  // Counted before anything is checked, in one step (auth.ts hit).
  const ipBucket = await bucket('signup-ip', clientIp(request));
  const [ipCount] = await hits(env, [hit(env, ipBucket, SIGNUP_WINDOW, now)]);
  if (ipCount! > SIGNUP_LIMIT) throw new HttpError(429, 'too_many');
  const name = v.name(body.name);
  const email = v.email(body.email);
  const key = v.key(body.key);
  if (body.over13 !== true) throw new HttpError(400, 'over13_required');
  if (name === null) throw new HttpError(400, 'bad_name');
  if (email === null || email === adminLogin(env)) throw new HttpError(400, 'bad_email');
  if (key === null) throw new HttpError(400, 'bad_key');
  const existing = await env.DB.prepare('SELECT id FROM users WHERE login = ?1')
    .bind(email)
    .first();
  if (existing !== null) throw new HttpError(409, 'email_taken');
  const id = newUserId();
  const { salt, key_hash } = await hashKey(key);
  await env.DB.prepare(
    `INSERT INTO users (id, login, email, name, role, salt, key_hash, over13, created_at, last_login_at)
     VALUES (?1, ?2, ?2, ?3, 'user', ?4, ?5, 1, ?6, ?6)`,
  )
    .bind(id, email, name, salt, key_hash, now)
    .run();
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
  await env.DB.prepare("UPDATE users SET key_hash = ?2 WHERE login = ?1 AND role = 'admin'")
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
  const accountBucket = await bucket('login-account', raw);
  const isAdmin = raw === adminLogin(env);
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
  } else {
    const row = await env.DB.prepare("SELECT * FROM users WHERE login = ?1 AND role = 'user'")
      .bind(raw)
      .first<UserRow>();
    if (row !== null && (await keyMatches(row, key))) user = row;
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
  const token = await createSession(env, user.id, now);
  if (user.role === 'admin') await audit(env, now, user, 'admin_login', null);
  if (Math.random() < 0.05) await sweep(env, now);
  return json(200, { token, user: publicUser({ ...user, last_login_at: now }) });
}

export async function logout(env: Env, request: Request, now: number): Promise<Response> {
  const session = await requireSession(env, request, now);
  await env.DB.prepare('DELETE FROM sessions WHERE token_hash = ?1').bind(session.tokenHash).run();
  return json(200, { ok: true });
}

export async function me(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  return json(200, { user: publicUser(user) });
}

/**
 * Name, email and password changes. A new email or password needs the current
 * key; the browser derives the new key from the (new) email and password. Any
 * key change signs out every other session and hands this one a new token.
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
    const next = v.key(body.new_key);
    if (current === null || !(await keyMatches(user, current)))
      throw new HttpError(403, 'wrong_password');
    // A new email changes the login the key is derived from, so it always comes with a new key.
    if (next === null) throw new HttpError(400, 'bad_key');
    if (wantsEmail) {
      const email = v.email(body.email);
      if (email === null || email === adminLogin(env)) throw new HttpError(400, 'bad_email');
      if (email !== user.email) {
        const taken = await env.DB.prepare('SELECT id FROM users WHERE login = ?1')
          .bind(email)
          .first();
        if (taken !== null) throw new HttpError(409, 'email_taken');
      }
      sets.push('email', 'login');
      values.push(email, email);
    }
    const { salt, key_hash } = await hashKey(next);
    sets.push('salt', 'key_hash');
    values.push(salt, key_hash);
  }
  if (sets.length === 0) throw new HttpError(400, 'nothing_to_change');
  const assignments = sets.map((column, i) => `${column} = ?${i + 2}`).join(', ');
  await env.DB.prepare(`UPDATE users SET ${assignments} WHERE id = ?1`)
    .bind(user.id, ...values)
    .run();
  let token: string | undefined;
  if (wantsEmail || wantsKey) {
    await revokeSessions(env, user.id);
    token = await createSession(env, user.id, now);
  }
  const row = await env.DB.prepare('SELECT * FROM users WHERE id = ?1')
    .bind(user.id)
    .first<UserRow>();
  return json(
    200,
    token === undefined ? { user: publicUser(row!) } : { token, user: publicUser(row!) },
  );
}

export async function deleteMe(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  if (user.role === 'admin') throw new HttpError(400, 'admin_managed');
  const key = v.key(body.key);
  if (key === null || !(await keyMatches(user, key))) throw new HttpError(403, 'wrong_password');
  // Sessions go with the row (ON DELETE CASCADE); deleted explicitly too in case foreign keys are off.
  await env.DB.batch([
    env.DB.prepare('DELETE FROM sessions WHERE user_id = ?1').bind(user.id),
    env.DB.prepare('DELETE FROM users WHERE id = ?1').bind(user.id),
  ]);
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

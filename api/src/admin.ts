/** Admin-only routes and the public list of manual statuses. Every admin route re-reads the role. */

import { audit } from './account';
import { daysLeft, endOfDay, listedDays, storedDays, timeZone } from './days';
import { DAY_MS, hashKey, requireAdmin, revokeSessions, schoolsOf, type UserRow } from './auth';
import { HttpError, json, readBody, type Env } from './http';
import { isoSeconds } from './util';
import * as v from './validate';

const PAGE_SIZE = 50;

export async function summary(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const [counts, overrides] = await env.DB.batch<Record<string, number>>([
    env.DB.prepare(
      `SELECT COUNT(*) AS total,
              SUM(CASE WHEN created_at > ?1 THEN 1 ELSE 0 END) AS day,
              SUM(CASE WHEN created_at > ?2 THEN 1 ELSE 0 END) AS week,
              SUM(CASE WHEN disabled != 0 THEN 1 ELSE 0 END) AS disabled,
              SUM(CASE WHEN last_login_at > ?2 THEN 1 ELSE 0 END) AS active_week
         FROM users WHERE role = 'user'`,
    ).bind(now - DAY_MS, now - 7 * DAY_MS),
    env.DB.prepare('SELECT COUNT(*) AS active FROM overrides WHERE expires_at > ?1').bind(now),
  ]);
  const c = counts!.results[0] ?? {};
  return json(200, {
    accounts: {
      total: c.total ?? 0,
      new_day: c.day ?? 0,
      new_week: c.week ?? 0,
      disabled: c.disabled ?? 0,
      active_week: c.active_week ?? 0,
    },
    overrides_active: overrides!.results[0]?.active ?? 0,
    generated_at: isoSeconds(now),
  });
}

function escapeLike(text: string): string {
  return text.replace(/[\\%_]/g, (c) => `\\${c}`);
}

export async function users(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const url = new URL(request.url);
  const q = (url.searchParams.get('q') ?? '').trim().toLowerCase().slice(0, 100);
  const page = Math.max(
    1,
    Math.min(10_000, Number.parseInt(url.searchParams.get('page') ?? '1', 10) || 1),
  );
  const pattern = `%${escapeLike(q)}%`;
  const where = "(?1 = '' OR lower(name) LIKE ?2 ESCAPE '\\' OR login LIKE ?2 ESCAPE '\\')";
  const [rows, total] = await env.DB.batch<UserRow & { n?: number }>([
    env.DB.prepare(
      `SELECT * FROM users WHERE ${where} ORDER BY created_at DESC LIMIT ?3 OFFSET ?4`,
    ).bind(q, pattern, PAGE_SIZE, (page - 1) * PAGE_SIZE),
    env.DB.prepare(`SELECT COUNT(*) AS n FROM users WHERE ${where}`).bind(q, pattern),
  ]);
  return json(200, {
    users: rows!.results.map((u) => ({
      id: u.id,
      name: u.name,
      email: u.email,
      role: u.role,
      created_at: isoSeconds(u.created_at),
      last_login_at: u.last_login_at === null ? null : isoSeconds(u.last_login_at),
      schools: schoolsOf(u).length,
      disabled: u.disabled !== 0,
    })),
    total: total!.results[0]?.n ?? 0,
    page,
    page_size: PAGE_SIZE,
  });
}

async function targetUser(env: Env, id: string): Promise<UserRow> {
  if (!/^[0-9a-f]{32}$/.test(id)) throw new HttpError(404, 'not_found');
  const row = await env.DB.prepare('SELECT * FROM users WHERE id = ?1').bind(id).first<UserRow>();
  if (row === null) throw new HttpError(404, 'not_found');
  if (row.role === 'admin') throw new HttpError(400, 'admin_managed');
  return row;
}

/** The admin's browser makes the temporary password and derives its key; only the key arrives. */
export async function resetPassword(
  env: Env,
  request: Request,
  now: number,
  id: string,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const body = await readBody(request);
  const target = await targetUser(env, id);
  const key = v.key(body.key);
  if (key === null) throw new HttpError(400, 'bad_key');
  const { salt, key_hash } = await hashKey(key);
  await env.DB.prepare('UPDATE users SET salt = ?2, key_hash = ?3 WHERE id = ?1')
    .bind(id, salt, key_hash)
    .run();
  await revokeSessions(env, id);
  await audit(env, now, admin, 'reset_password', target.email ?? id);
  return json(200, { ok: true });
}

export async function setDisabled(
  env: Env,
  request: Request,
  now: number,
  id: string,
  disabled: boolean,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const target = await targetUser(env, id);
  await env.DB.prepare('UPDATE users SET disabled = ?2 WHERE id = ?1')
    .bind(id, disabled ? 1 : 0)
    .run();
  if (disabled) await revokeSessions(env, id);
  await audit(env, now, admin, disabled ? 'disable_user' : 'enable_user', target.email ?? id);
  return json(200, { ok: true });
}

export async function deleteUser(
  env: Env,
  request: Request,
  now: number,
  id: string,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const target = await targetUser(env, id);
  await env.DB.batch([
    env.DB.prepare('DELETE FROM sessions WHERE user_id = ?1').bind(id),
    env.DB.prepare('DELETE FROM users WHERE id = ?1').bind(id),
  ]);
  await audit(env, now, admin, 'delete_user', target.email ?? id);
  return json(200, { ok: true });
}

interface OverrideRow {
  key: string;
  scope: v.Scope;
  target_id: string;
  status: v.Status;
  minutes: number | null;
  at_local_time: string | null;
  note: string | null;
  set_at: number;
  expires_at: number;
  set_by: string | null;
  /** The listed school-local days, a JSON array of YYYY-MM-DD (migration 0002). */
  days: string | null;
  /** Their IANA time zone; null on a row from before days were stored. */
  time_zone: string | null;
}

/**
 * What anyone may see of a manual status: never the note or who set it. `days`
 * holds the listed days whose end has not passed at `now` (all of them for a
 * row that has ended).
 */
function publicOverride(row: OverrideRow, now: number) {
  const { days, time_zone } = storedDays(row.days, row.time_zone, row.expires_at);
  return {
    scope: row.scope,
    id: row.target_id,
    status: row.status,
    minutes: row.minutes,
    at_local_time: row.at_local_time,
    days: row.expires_at > now ? daysLeft(days, time_zone, now) : days,
    time_zone,
    set_at: isoSeconds(row.set_at),
    expires_at: isoSeconds(row.expires_at),
  };
}

export async function publicOverrides(
  env: Env,
  now: number,
  cors: Record<string, string>,
): Promise<Response> {
  const { results } = await env.DB.prepare(
    'SELECT * FROM overrides WHERE expires_at > ?1 ORDER BY scope, target_id',
  )
    .bind(now)
    .all<OverrideRow>();
  const overrides = results
    .map((row) => publicOverride(row, now))
    .filter((row) => row.days.length > 0);
  return json(
    200,
    { generated_at: isoSeconds(now), overrides },
    { ...cors, 'Cache-Control': 'public, max-age=30' },
  );
}

export async function listOverrides(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const { results } = await env.DB.prepare(
    'SELECT * FROM overrides WHERE expires_at > ?1 ORDER BY set_at DESC LIMIT 200',
  )
    .bind(now - 7 * DAY_MS)
    .all<OverrideRow>();
  return json(200, {
    overrides: results.map((row) => ({
      key: row.key,
      ...publicOverride(row, now),
      note: row.note,
      set_by: row.set_by,
      active: row.expires_at > now,
    })),
    generated_at: isoSeconds(now),
  });
}

export async function putOverride(env: Env, request: Request, now: number): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const body = await readBody(request);
  const scope = v.oneOf(v.SCOPES, body.scope);
  if (scope === null) throw new HttpError(400, 'bad_scope');
  const id = v.targetId(scope, body.id);
  if (id === null) throw new HttpError(400, 'bad_id');
  const status = v.oneOf(v.STATUSES, body.status);
  if (status === null) throw new HttpError(400, 'bad_status');
  let minutes: number | null = null;
  let atLocalTime: string | null = null;
  if (status === 'delayed') {
    if (
      typeof body.minutes !== 'number' ||
      !Number.isInteger(body.minutes) ||
      body.minutes < 1 ||
      body.minutes > 240
    )
      throw new HttpError(400, 'bad_minutes');
    minutes = body.minutes;
  } else if (body.minutes !== undefined && body.minutes !== null)
    throw new HttpError(400, 'bad_minutes');
  if (status === 'early_dismissal') {
    atLocalTime = v.localTime(body.at_local_time);
    if (atLocalTime === null) throw new HttpError(400, 'bad_time');
  } else if (body.at_local_time !== undefined && body.at_local_time !== null)
    throw new HttpError(400, 'bad_time');
  let note: string | null = null;
  if (body.note !== undefined && body.note !== null && body.note !== '') {
    note = v.plain(body.note, 1, 200);
    if (note === null) throw new HttpError(400, 'bad_note');
  }
  // Which days, in the school's own zone: its today, its tomorrow, or both. The
  // status ends when its last day ends there.
  const zone = timeZone(body.time_zone);
  if (zone === null) throw new HttpError(400, 'bad_time_zone');
  const days = listedDays(body.days, zone, now);
  if (days === null) throw new HttpError(400, 'bad_days');
  const expires = endOfDay(days[days.length - 1]!, zone);
  if (expires <= now) throw new HttpError(400, 'bad_days');
  const key = `${scope}:${id}`;
  // One status per district or school: saving again replaces it, days and all.
  await env.DB.prepare(
    `INSERT INTO overrides (key, scope, target_id, status, minutes, at_local_time, note, set_at, expires_at, set_by, days, time_zone)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
     ON CONFLICT (key) DO UPDATE SET status = ?4, minutes = ?5, at_local_time = ?6, note = ?7,
       set_at = ?8, expires_at = ?9, set_by = ?10, days = ?11, time_zone = ?12`,
  )
    .bind(
      key,
      scope,
      id,
      status,
      minutes,
      atLocalTime,
      note,
      now,
      expires,
      admin.name,
      JSON.stringify(days),
      zone,
    )
    .run();
  await audit(env, now, admin, 'set_status', key, {
    status,
    minutes,
    at_local_time: atLocalTime,
    days,
    time_zone: zone,
    expires_at: isoSeconds(expires),
  });
  const row = await env.DB.prepare('SELECT * FROM overrides WHERE key = ?1')
    .bind(key)
    .first<OverrideRow>();
  return json(200, {
    override: {
      key,
      ...publicOverride(row!, now),
      note: row!.note,
      set_by: row!.set_by,
      active: true,
    },
  });
}

export async function deleteOverride(
  env: Env,
  request: Request,
  now: number,
  key: string,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  if (!/^(?:district|school):[0-9A-Z]{7,12}$/.test(key)) throw new HttpError(404, 'not_found');
  const result = await env.DB.prepare('DELETE FROM overrides WHERE key = ?1').bind(key).run();
  if ((result.meta.changes ?? 0) === 0) throw new HttpError(404, 'not_found');
  await audit(env, now, admin, 'clear_status', key);
  return json(200, { ok: true });
}

export async function auditLog(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const url = new URL(request.url);
  const page = Math.max(
    1,
    Math.min(10_000, Number.parseInt(url.searchParams.get('page') ?? '1', 10) || 1),
  );
  const { results } = await env.DB.prepare(
    'SELECT * FROM audit ORDER BY id DESC LIMIT ?1 OFFSET ?2',
  )
    .bind(PAGE_SIZE, (page - 1) * PAGE_SIZE)
    .all<{
      id: number;
      at: number;
      actor_name: string | null;
      action: string;
      target: string | null;
      detail: string | null;
    }>();
  return json(200, {
    entries: results.map((e) => ({
      id: e.id,
      at: isoSeconds(e.at),
      actor: e.actor_name,
      action: e.action,
      target: e.target,
      detail: e.detail === null ? null : (JSON.parse(e.detail) as unknown),
    })),
    page,
    page_size: PAGE_SIZE,
  });
}

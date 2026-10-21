/**
 * Notifications (docs/notify.md): the VAPID public key, an account's push subscriptions
 * (one per browser that turned notifications on, up to MAX_DEVICES) and its settings.
 *
 * The Worker only stores. Nothing is sent from here: the sender runs in GitHub Actions
 * (pipeline/snowlight/notify), reads these tables over the Cloudflare API and signs with
 * the VAPID private key, which the Worker never reads. Every route is one or two small D1
 * statements, well inside the free plan's 10 ms of CPU.
 */

import { endPushFor, requireSession } from './auth';
import { HttpError, json, readBody, type Env } from './http';
import * as v from './validate';

/** Browsers per account; a new one beyond this drops the oldest. */
export const MAX_DEVICES = 5;
export const THRESHOLDS = [30, 50, 70] as const;
export const MAX_ENDPOINT = 1024;

/**
 * The push services the sender will post to, by host: Chrome, Edge, Firefox and Safari
 * (and the browsers built on them). An endpoint anywhere else is refused, so a
 * subscription can never point the sender at another server.
 */
export const PUSH_HOSTS: readonly RegExp[] = [
  /^fcm\.googleapis\.com$/,
  /^android\.googleapis\.com$/,
  /^updates\.push\.services\.mozilla\.com$/,
  /^web\.push\.apple\.com$/,
  /^[a-z0-9-]+\.notify\.windows\.com$/,
];

/** base64url of an uncompressed P-256 point (65 bytes, 0x04 first) and of 16 random bytes. */
const P256DH = /^B[A-Za-z0-9_-]{86}$/;
const AUTH = /^[A-Za-z0-9_-]{22}$/;
/** A whole or half hour, 24-hour clock. */
const HALF_HOUR = /^(?:[01]\d|2[0-3]):[03]0$/;
const HOUR = /^(?:[01]\d|2[0-3]):00$/;

export interface NotifySettings {
  status: boolean;
  chance: boolean;
  threshold: (typeof THRESHOLDS)[number];
  night_before: boolean;
  night_time: string;
  quiet_from: string;
  quiet_to: string;
}

export const DEFAULTS: Readonly<NotifySettings> = Object.freeze({
  status: true,
  chance: true,
  threshold: 50,
  night_before: false,
  night_time: '20:00',
  quiet_from: '22:00',
  quiet_to: '05:00',
});

interface SettingsRow {
  status: number;
  chance: number;
  threshold: number;
  night_before: number;
  night_time: string;
  quiet_from: string;
  quiet_to: string;
}

function fromRow(row: SettingsRow | null): NotifySettings {
  if (row === null) return { ...DEFAULTS };
  return {
    status: row.status !== 0,
    chance: row.chance !== 0,
    threshold: (THRESHOLDS as readonly number[]).includes(row.threshold)
      ? (row.threshold as NotifySettings['threshold'])
      : DEFAULTS.threshold,
    night_before: row.night_before !== 0,
    night_time: row.night_time,
    quiet_from: row.quiet_from,
    quiet_to: row.quiet_to,
  };
}

/** A push service address the sender may post to, or null. */
export function endpoint(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > MAX_ENDPOINT) return null;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' || url.username !== '' || url.password !== '' || url.port !== '')
    return null;
  if (url.hash !== '' || url.href !== value) return null;
  return PUSH_HOSTS.some((host) => host.test(url.hostname)) ? value : null;
}

/** GET /v1/push/key: the VAPID public key the browser subscribes with (404 until api.yml made one). */
export async function pushKey(env: Env): Promise<Response> {
  const row = await env.DB.prepare("SELECT value FROM settings WHERE name = 'vapid_public'")
    .first<{ value: string }>()
    .catch(() => null);
  if (row === null || !P256DH.test(row.value)) throw new HttpError(404, 'push_off');
  return json(200, { key: row.value });
}

/** How many browsers get the account's notifications: those whose sign-in still lasts. */
async function devices(env: Env, userId: string, now: number): Promise<number> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM push_subscriptions p
       JOIN sessions s ON s.token_hash = p.session_hash
      WHERE p.user_id = ?1 AND s.expires_at > ?2`,
  )
    .bind(userId, now)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

/**
 * PUT /v1/me/push {subscription: {endpoint, keys: {p256dh, auth}}}: keeps this browser's
 * subscription for the account and this sign-in (the browser gets notifications while the
 * sign-in lasts; signing in again there and sending it again brings them back). An account
 * keeps its newest MAX_DEVICES. The page sends it only for the account that turned this
 * browser on (account/notify.ts), so a browser never moves to another account unasked.
 */
export async function putPush(env: Env, request: Request, now: number): Promise<Response> {
  const { user, tokenHash } = await requireSession(env, request, now);
  const body = await readBody(request);
  const subscription = body.subscription;
  if (!v.isRecord(subscription) || !v.isRecord(subscription.keys))
    throw new HttpError(400, 'bad_subscription');
  const address = endpoint(subscription.endpoint);
  const p256dh = subscription.keys.p256dh;
  const auth = subscription.keys.auth;
  if (
    address === null ||
    typeof p256dh !== 'string' ||
    !P256DH.test(p256dh) ||
    typeof auth !== 'string' ||
    !AUTH.test(auth)
  )
    throw new HttpError(400, 'bad_subscription');
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO push_subscriptions (endpoint, user_id, session_hash, p256dh, auth, created_at)
       VALUES (?1, ?2, ?6, ?3, ?4, ?5)
       ON CONFLICT (endpoint) DO UPDATE SET
         user_id = ?2, session_hash = ?6, p256dh = ?3, auth = ?4, failures = 0, failing_since = NULL,
         created_at = CASE WHEN push_subscriptions.user_id = ?2 THEN push_subscriptions.created_at ELSE ?5 END`,
    ).bind(address, user.id, p256dh, auth, now, tokenHash),
    env.DB.prepare(
      `DELETE FROM push_subscriptions WHERE user_id = ?1 AND endpoint NOT IN (
         SELECT endpoint FROM push_subscriptions WHERE user_id = ?1
          ORDER BY created_at DESC, endpoint LIMIT ${MAX_DEVICES})`,
    ).bind(user.id),
  ]);
  return json(200, { devices: await devices(env, user.id, now) });
}

/**
 * DELETE /v1/me/push {endpoint}: this browser stops getting the account's notifications;
 * {all: true}: every browser does (Settings > Notifications, Turn off on all devices).
 */
export async function deletePush(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  if (body.all === true) {
    await endPushFor(env, user.id).run();
    return json(200, { devices: 0 });
  }
  if (typeof body.endpoint !== 'string' || body.endpoint.length > MAX_ENDPOINT)
    throw new HttpError(400, 'bad_subscription');
  await env.DB.prepare('DELETE FROM push_subscriptions WHERE user_id = ?1 AND endpoint = ?2')
    .bind(user.id, body.endpoint)
    .run();
  return json(200, { devices: await devices(env, user.id, now) });
}

async function readSettings(env: Env, userId: string): Promise<NotifySettings> {
  const row = await env.DB.prepare(
    `SELECT status, chance, threshold, night_before, night_time, quiet_from, quiet_to
       FROM notify_settings WHERE user_id = ?1`,
  )
    .bind(userId)
    .first<SettingsRow>();
  return fromRow(row);
}

/** GET /v1/me/notify: the account's settings and how many browsers get its notifications. */
export async function getNotify(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  return json(200, {
    settings: await readSettings(env, user.id),
    devices: await devices(env, user.id, now),
  });
}

/** PATCH /v1/me/notify: changes any of the settings; anything out of range refuses the whole change. */
export async function patchNotify(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  const next = await readSettings(env, user.id);
  const known = new Set(Object.keys(DEFAULTS));
  for (const field of Object.keys(body))
    if (!known.has(field)) throw new HttpError(400, 'bad_settings');
  for (const field of ['status', 'chance', 'night_before'] as const) {
    const value = body[field];
    if (value === undefined) continue;
    if (typeof value !== 'boolean') throw new HttpError(400, 'bad_settings');
    next[field] = value;
  }
  if (body.threshold !== undefined) {
    if (!(THRESHOLDS as readonly unknown[]).includes(body.threshold))
      throw new HttpError(400, 'bad_settings');
    next.threshold = body.threshold as NotifySettings['threshold'];
  }
  if (body.night_time !== undefined) {
    if (typeof body.night_time !== 'string' || !HALF_HOUR.test(body.night_time))
      throw new HttpError(400, 'bad_settings');
    next.night_time = body.night_time;
  }
  for (const field of ['quiet_from', 'quiet_to'] as const) {
    const value = body[field];
    if (value === undefined) continue;
    if (typeof value !== 'string' || !HOUR.test(value)) throw new HttpError(400, 'bad_settings');
    next[field] = value;
  }
  await env.DB.prepare(
    `INSERT INTO notify_settings
       (user_id, status, chance, threshold, night_before, night_time, quiet_from, quiet_to, updated_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
     ON CONFLICT (user_id) DO UPDATE SET
       status = ?2, chance = ?3, threshold = ?4, night_before = ?5, night_time = ?6,
       quiet_from = ?7, quiet_to = ?8, updated_at = ?9`,
  )
    .bind(
      user.id,
      next.status ? 1 : 0,
      next.chance ? 1 : 0,
      next.threshold,
      next.night_before ? 1 : 0,
      next.night_time,
      next.quiet_from,
      next.quiet_to,
      now,
    )
    .run();
  return json(200, { settings: next, devices: await devices(env, user.id, now) });
}

/** The statements that remove everything notifications keep for an account (account deletion). */
export function eraseNotify(env: Env, userId: string): D1PreparedStatement[] {
  return [
    env.DB.prepare('DELETE FROM push_subscriptions WHERE user_id = ?1').bind(userId),
    env.DB.prepare('DELETE FROM notify_settings WHERE user_id = ?1').bind(userId),
    env.DB.prepare('DELETE FROM notify_sent WHERE user_id = ?1').bind(userId),
  ];
}

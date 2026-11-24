/**
 * Flights trips and Flights alert choices (flights spec D12, D19; docs/flights-trips.md).
 *
 * The Worker only stores. The chance, Backup plans and every alert are worked out in the browser
 * from the published files and in the Actions sender (pipeline/snowlight/notify flights), so each
 * route here is one or two small D1 statements, well inside the free plan's 10 ms of CPU.
 */

import { requireSession } from './auth';
import { HttpError, json, readBody, type Env } from './http';
import { randomHex } from './util';
import * as v from './validate';

/** Trips an account keeps (past ones included until the daily sweep drops them). */
export const MAX_TRIPS = 20;
/** A past trip is kept this many days after its day, folded away, then swept. */
export const KEEP_PAST_DAYS = 14;
/** How far ahead a trip may be saved. */
export const MAX_AHEAD_DAYS = 331;
export const TICKETS = ['basic', 'regular', 'premium', 'unsure'] as const;
export const SOURCES = ['typed', 'calendar', 'gmail'] as const;
export const FLIGHT_THRESHOLDS = [30, 50, 70] as const;

const CARRIER = /^[A-Z0-9]{2}$/;
const AIRPORT = /^[A-Z0-9]{3}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const LOCAL_AT = /^(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d)$/;
const HALF_HOUR = /^(?:1[7-9]|2[01]):[03]0$/;
const TRIP_ID = /^[0-9a-f]{32}$/;

export interface Trip {
  id: string;
  carrier: string;
  number: number;
  from: string;
  to: string;
  day: string;
  leaves: number;
  lands: number;
  ticket: (typeof TICKETS)[number];
  ticket_asked: boolean;
  need_by: string | null;
  source: (typeof SOURCES)[number];
}

interface TripRow {
  id: string;
  carrier: string;
  number: number;
  from_airport: string;
  to_airport: string;
  day: string;
  leaves: number;
  lands: number;
  ticket: string;
  ticket_asked: number;
  need_by: string | null;
  source: string;
}

function tripOf(row: TripRow): Trip {
  return {
    id: row.id,
    carrier: row.carrier,
    number: row.number,
    from: row.from_airport,
    to: row.to_airport,
    day: row.day,
    leaves: row.leaves,
    lands: row.lands,
    ticket: v.oneOf(TICKETS, row.ticket) ?? 'unsure',
    ticket_asked: row.ticket_asked !== 0,
    need_by: row.need_by,
    source: v.oneOf(SOURCES, row.source) ?? 'typed',
  };
}

const COLUMNS =
  'id, carrier, number, from_airport, to_airport, day, leaves, lands, ticket, ticket_asked, need_by, source';

/** A real calendar day "YYYY-MM-DD", as its UTC noon, or null. */
function dayMs(value: unknown): number | null {
  if (typeof value !== 'string' || !DAY.test(value)) return null;
  const ms = Date.parse(`${value}T12:00:00Z`);
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 10) !== value) return null;
  return ms;
}

function minute(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 1439
    ? value
    : null;
}

/** "I need to be there by": a real local date and time, from the trip's day to 3 days after. */
function needBy(value: unknown, day: string): string | null | undefined {
  if (value === null) return null;
  if (typeof value !== 'string') return undefined;
  const match = LOCAL_AT.exec(value);
  const at = match === null ? null : dayMs(match[1]);
  const from = dayMs(day);
  if (at === null || from === null) return undefined;
  const ahead = (at - from) / 86_400_000;
  return ahead >= 0 && ahead <= 3 ? value : undefined;
}

async function readTrips(env: Env, userId: string): Promise<Trip[]> {
  const { results } = await env.DB.prepare(
    `SELECT ${COLUMNS} FROM trips WHERE user_id = ?1 ORDER BY day, leaves, carrier, number`,
  )
    .bind(userId)
    .all<TripRow>();
  return results.map(tripOf);
}

/** GET /v1/me/trips: the account's trips, soonest first. */
export async function listTrips(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  return json(200, { trips: await readTrips(env, user.id) });
}

/**
 * POST /v1/me/trips {carrier, number, from, to, day, leaves, lands, ticket?, need_by?, source?}:
 * saves a flight. The same flight on the same day again keeps one trip, with the times sent and
 * its ticket type kept unless one is sent. Up to MAX_TRIPS.
 */
export async function addTrip(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  const carrier =
    typeof body.carrier === 'string' && CARRIER.test(body.carrier) ? body.carrier : null;
  const number =
    typeof body.number === 'number' &&
    Number.isInteger(body.number) &&
    body.number >= 1 &&
    body.number <= 9999
      ? body.number
      : null;
  const from = typeof body.from === 'string' && AIRPORT.test(body.from) ? body.from : null;
  const to = typeof body.to === 'string' && AIRPORT.test(body.to) ? body.to : null;
  const at = dayMs(body.day);
  const leaves = minute(body.leaves);
  const lands = minute(body.lands);
  const ticket = body.ticket === undefined ? null : v.oneOf(TICKETS, body.ticket);
  const source = body.source === undefined ? 'typed' : v.oneOf(SOURCES, body.source);
  if (
    carrier === null ||
    number === null ||
    from === null ||
    to === null ||
    from === to ||
    at === null ||
    leaves === null ||
    lands === null ||
    (body.ticket !== undefined && ticket === null) ||
    source === null
  )
    throw new HttpError(400, 'bad_trip');
  const day = body.day as string;
  // From yesterday (a time zone behind) to about 11 months ahead, as airlines sell.
  const ahead =
    (at - Date.parse(`${new Date(now).toISOString().slice(0, 10)}T12:00:00Z`)) / 86_400_000;
  if (ahead < -1 || ahead > MAX_AHEAD_DAYS) throw new HttpError(400, 'bad_day');
  const need = body.need_by === undefined ? null : needBy(body.need_by, day);
  if (need === undefined) throw new HttpError(400, 'bad_trip');
  const count = await env.DB.prepare(
    `SELECT COUNT(*) AS n, SUM(CASE WHEN carrier = ?2 AND number = ?3 AND from_airport = ?4 AND day = ?5 THEN 1 ELSE 0 END) AS same
       FROM trips WHERE user_id = ?1`,
  )
    .bind(user.id, carrier, number, from, day)
    .first<{ n: number; same: number | null }>();
  if ((count?.same ?? 0) === 0 && (count?.n ?? 0) >= MAX_TRIPS)
    throw new HttpError(409, 'too_many_trips');
  const row = await env.DB.prepare(
    `INSERT INTO trips (id, user_id, carrier, number, from_airport, to_airport, day, leaves, lands,
                        ticket, ticket_asked, need_by, source, created_at, updated_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, COALESCE(?10, 'unsure'), ?11, ?12, ?13, ?14, ?14)
     ON CONFLICT (user_id, carrier, number, from_airport, day) DO UPDATE SET
       to_airport = ?6, leaves = ?8, lands = ?9,
       ticket = COALESCE(?10, trips.ticket),
       ticket_asked = MAX(trips.ticket_asked, ?11),
       need_by = CASE WHEN ?15 THEN ?12 ELSE trips.need_by END,
       updated_at = ?14
     RETURNING ${COLUMNS}`,
  )
    .bind(
      randomHex(16),
      user.id,
      carrier,
      number,
      from,
      to,
      day,
      leaves,
      lands,
      ticket,
      ticket === null ? 0 : 1,
      need,
      source,
      now,
      body.need_by === undefined ? 0 : 1,
    )
    .first<TripRow>();
  if (row === null) throw new HttpError(500, 'server');
  return json(201, { trip: tripOf(row) });
}

/** PATCH /v1/me/trips/:id {ticket?, ticket_asked?, need_by?}: the trip's own choices. */
export async function patchTrip(
  env: Env,
  request: Request,
  now: number,
  id: string,
): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  if (!TRIP_ID.test(id)) throw new HttpError(404, 'not_found');
  const body = await readBody(request);
  for (const field of Object.keys(body))
    if (!['ticket', 'ticket_asked', 'need_by'].includes(field))
      throw new HttpError(400, 'bad_trip');
  const had = await env.DB.prepare(`SELECT ${COLUMNS} FROM trips WHERE id = ?1 AND user_id = ?2`)
    .bind(id, user.id)
    .first<TripRow>();
  if (had === null) throw new HttpError(404, 'not_found');
  const ticket = body.ticket === undefined ? had.ticket : v.oneOf(TICKETS, body.ticket);
  if (ticket === null) throw new HttpError(400, 'bad_trip');
  if (body.ticket_asked !== undefined && body.ticket_asked !== true)
    throw new HttpError(400, 'bad_trip');
  const asked = body.ticket !== undefined || body.ticket_asked === true || had.ticket_asked !== 0;
  const need = body.need_by === undefined ? had.need_by : needBy(body.need_by, had.day);
  if (need === undefined) throw new HttpError(400, 'bad_trip');
  const row = await env.DB.prepare(
    `UPDATE trips SET ticket = ?3, ticket_asked = ?4, need_by = ?5, updated_at = ?6
      WHERE id = ?1 AND user_id = ?2 RETURNING ${COLUMNS}`,
  )
    .bind(id, user.id, ticket, asked ? 1 : 0, need, now)
    .first<TripRow>();
  if (row === null) throw new HttpError(404, 'not_found');
  return json(200, { trip: tripOf(row) });
}

/** DELETE /v1/me/trips/:id: the trip, with what was sent for it. */
export async function deleteTrip(
  env: Env,
  request: Request,
  now: number,
  id: string,
): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  if (!TRIP_ID.test(id)) throw new HttpError(404, 'not_found');
  const [gone] = await env.DB.batch([
    env.DB.prepare('DELETE FROM trips WHERE id = ?1 AND user_id = ?2').bind(id, user.id),
    env.DB.prepare('DELETE FROM flights_sent WHERE trip_id = ?1 AND user_id = ?2').bind(
      id,
      user.id,
    ),
  ]);
  if ((gone?.meta.changes ?? 0) === 0) throw new HttpError(404, 'not_found');
  return json(200, { ok: true });
}

// Flights alert choices ------------------------------------------------------------------------

export interface FlightsNotify {
  alerts: boolean;
  threshold: (typeof FLIGHT_THRESHOLDS)[number];
  night_before: boolean;
  night_time: string;
  email: boolean;
}

export const FLIGHTS_DEFAULTS: Readonly<FlightsNotify> = Object.freeze({
  alerts: true,
  threshold: 30,
  night_before: true,
  night_time: '20:00',
  email: true,
});

interface NotifyRow {
  alerts: number;
  threshold: number;
  night_before: number;
  night_time: string;
  email: number;
}

async function readFlightsNotify(env: Env, userId: string): Promise<FlightsNotify> {
  const row = await env.DB.prepare(
    'SELECT alerts, threshold, night_before, night_time, email FROM flights_notify WHERE user_id = ?1',
  )
    .bind(userId)
    .first<NotifyRow>();
  if (row === null) return { ...FLIGHTS_DEFAULTS };
  return {
    alerts: row.alerts !== 0,
    threshold: (FLIGHT_THRESHOLDS as readonly number[]).includes(row.threshold)
      ? (row.threshold as FlightsNotify['threshold'])
      : FLIGHTS_DEFAULTS.threshold,
    night_before: row.night_before !== 0,
    night_time: row.night_time,
    email: row.email !== 0,
  };
}

/** GET /v1/me/flights/notify. */
export async function getFlightsNotify(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  return json(200, { settings: await readFlightsNotify(env, user.id) });
}

/** PATCH /v1/me/flights/notify: any of the choices; anything out of range refuses the change. */
export async function patchFlightsNotify(
  env: Env,
  request: Request,
  now: number,
): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  const body = await readBody(request);
  const next = await readFlightsNotify(env, user.id);
  const known = new Set(Object.keys(FLIGHTS_DEFAULTS));
  for (const field of Object.keys(body))
    if (!known.has(field)) throw new HttpError(400, 'bad_settings');
  for (const field of ['alerts', 'night_before', 'email'] as const) {
    const value = body[field];
    if (value === undefined) continue;
    if (typeof value !== 'boolean') throw new HttpError(400, 'bad_settings');
    next[field] = value;
  }
  if (body.threshold !== undefined) {
    if (!(FLIGHT_THRESHOLDS as readonly unknown[]).includes(body.threshold))
      throw new HttpError(400, 'bad_settings');
    next.threshold = body.threshold as FlightsNotify['threshold'];
  }
  if (body.night_time !== undefined) {
    if (typeof body.night_time !== 'string' || !HALF_HOUR.test(body.night_time))
      throw new HttpError(400, 'bad_settings');
    next.night_time = body.night_time;
  }
  await env.DB.prepare(
    `INSERT INTO flights_notify (user_id, alerts, threshold, night_before, night_time, email, updated_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
     ON CONFLICT (user_id) DO UPDATE SET
       alerts = ?2, threshold = ?3, night_before = ?4, night_time = ?5, email = ?6, updated_at = ?7`,
  )
    .bind(
      user.id,
      next.alerts ? 1 : 0,
      next.threshold,
      next.night_before ? 1 : 0,
      next.night_time,
      next.email ? 1 : 0,
      now,
    )
    .run();
  return json(200, { settings: next });
}

/** The statements that remove an account's trips and Flights alerts (account deletion). */
export function eraseTrips(env: Env, userId: string): D1PreparedStatement[] {
  return [
    env.DB.prepare('DELETE FROM flights_sent WHERE user_id = ?1').bind(userId),
    env.DB.prepare('DELETE FROM trips WHERE user_id = ?1').bind(userId),
    env.DB.prepare('DELETE FROM flights_notify WHERE user_id = ?1').bind(userId),
  ];
}

/** The daily sweep's part: trips more than KEEP_PAST_DAYS past their day, with their log. */
export function sweepTrips(env: Env, now: number): D1PreparedStatement[] {
  const before = new Date(now - KEEP_PAST_DAYS * 86_400_000).toISOString().slice(0, 10);
  return [
    env.DB.prepare(
      'DELETE FROM flights_sent WHERE trip_id IN (SELECT id FROM trips WHERE day < ?1)',
    ).bind(before),
    env.DB.prepare('DELETE FROM trips WHERE day < ?1').bind(before),
  ];
}

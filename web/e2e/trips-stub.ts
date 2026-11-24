/**
 * What the trips checks (e2e/trips.spec.ts) and their pictures serve: a made-up accounts API with
 * the trips, Flights alert choices and Google routes (api/src/trips.ts, api/src/google.ts), and
 * SYNTHETIC flights files for one stormy morning at MCI. Every chance, usual flight, trip and
 * calendar event here is made up and lives only in these checks.
 */
import type { Page, Route } from '@playwright/test';

import { ACCOUNTS_API } from './accounts-server';

/** Monday, Jan 5, 2026, 8:00 am in Kansas City. */
export const TRIPS_NOW = new Date('2026-01-05T14:00:00Z');
export const TOKEN = 'T'.repeat(43);

const ROW = (n: number): number[] => [n, n, n, n, n];

function localDay(at: Date, zone: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(at);
}

function airport(code: string, zone: string, made: Date, dep: number[][]): Record<string, unknown> {
  return {
    code,
    today: localDay(made, zone),
    dep_canc: dep,
    dep_late: [ROW(60), ROW(60), ROW(60)],
    arr_canc: [ROW(10), ROW(10), ROW(10)],
    arr_late: [ROW(60), ROW(60), ROW(60)],
    rough: [10, 10, 10],
    runs: [null, null, null],
    usual: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
    rough_usual: 0,
    why: [[0], [0], []],
    programs: [],
    alerts: [],
    now: null,
  };
}

function usual(carrier: string, number: number, to: string, leaves: number, lands: number) {
  return {
    carrier,
    number,
    to_airport: to,
    leaves,
    lands,
    weekdays: 127,
    days: 30,
    cancelled: 0,
    late: 2,
  };
}

/** Snow at MCI this morning (a 25% cancel chance before noon), calm after; calm everywhere else. */
export async function serveTripFlights(page: Page, made: Date = TRIPS_NOW): Promise<void> {
  const at = made.toISOString().replace(/\.\d+Z$/, 'Z');
  const stamp = `${made.toISOString().slice(0, 16).replace(/[-:]/g, '')}Z`;
  const calm = [ROW(10), ROW(10), ROW(10)];
  const live = {
    schema_version: 1,
    generated_at: at,
    slot: 'slot-1',
    stamp,
    run: at,
    programs_at: at,
    alerts_at: at,
    weather_at: at,
    observed_at: at,
    airports: [
      airport('MCI', 'America/Chicago', made, [[250, 250, 20, 10, 10], ROW(10), ROW(10)]),
      airport('LAX', 'America/Los_Angeles', made, calm),
      airport('BUR', 'America/Los_Angeles', made, calm),
      airport('DEN', 'America/Denver', made, calm),
    ],
  };
  const routes: Record<string, unknown> = {
    mci: [
      usual('WN', 1234, 'LAX', 600, 720),
      usual('WN', 1500, 'LAX', 900, 1020),
      usual('AA', 88, 'LAX', 1080, 1200),
      usual('WN', 77, 'BUR', 1110, 1230),
      usual('WN', 300, 'DEN', 780, 840),
      usual('UA', 420, 'DEN', 640, 700),
      usual('UA', 420, 'LAX', 640, 760),
    ],
    den: [usual('WN', 400, 'LAX', 960, 1060), usual('WN', 401, 'LAX', 860, 960)],
  };
  await page.route('**/data/flights/**', async (route) => {
    const name = new URL(route.request().url()).pathname.replace(/^.*\/data\/flights\//, '');
    const code = /^routes\/([a-z0-9]{3})\.json$/.exec(name)?.[1];
    const body =
      name === 'latest.json'
        ? { schema_version: 1, generated_at: at, slot: 'slot-1', stamp }
        : name === 'live/slot-1.json'
          ? live
          : code !== undefined && routes[code] !== undefined
            ? {
                schema_version: 1,
                generated_at: at,
                code: code.toUpperCase(),
                months: [{ month: '2025-09', flights: routes[code] }],
              }
            : null;
    if (body === null) await route.fulfill({ status: 404, body: '' });
    else
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
  });
}

export interface StubTrip {
  id: string;
  carrier: string;
  number: number;
  from: string;
  to: string;
  day: string;
  leaves: number;
  lands: number;
  ticket: 'basic' | 'regular' | 'premium' | 'unsure';
  ticket_asked: boolean;
  need_by: string | null;
  source: 'typed' | 'calendar' | 'gmail';
}

/** An accounts API in memory with the trips routes; every request it was sent is kept. */
export class TripsApi {
  signedIn = true;
  trips: StubTrip[] = [];
  google: {
    configured: boolean;
    client_id: string | null;
    gmail_demo: boolean;
    gmail_client_id: string | null;
  } = {
    configured: false,
    client_id: null,
    gmail_demo: false,
    gmail_client_id: null,
  };
  connected = false;
  /** When the link was made (ms): an old one until a finish makes a new one. */
  since = Date.UTC(2026, 0, 2, 18);
  /** A connect Google refuses (a scope never asked for): the API also ends the old link. */
  finishRefused = false;
  events: Record<string, unknown>[] = [];
  flights = { alerts: true, threshold: 30, night_before: true, night_time: '20:00', email: true };
  sent: { method: string; path: string; body: unknown }[] = [];
  private next = 1;

  async attach(page: Page): Promise<void> {
    if (this.signedIn)
      await page.addInitScript((token) => {
        try {
          localStorage.setItem('snowlight:session', token);
        } catch {
          // A page with no storage: signed out.
        }
      }, TOKEN);
    await page.route(`${ACCOUNTS_API}/**`, (route) => this.answer(route));
  }

  private user(): Record<string, unknown> {
    return {
      id: 'a'.repeat(32),
      name: 'Pat Lee',
      email: 'pat@example.com',
      role: 'user',
      schools: [],
      created_at: '2026-10-20T00:00:00.000Z',
      username: 'pat',
      join_number: 7,
      username_required: false,
      renamed: false,
      needs_rekey: false,
    };
  }

  private async answer(route: Route): Promise<void> {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const cors = {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'Authorization, Content-Type',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    };
    if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    const body: unknown =
      request.postData() === null ? null : JSON.parse(request.postData() ?? 'null');
    this.sent.push({ method, path, body });
    const reply = (status: number, value: unknown) =>
      route.fulfill({
        status,
        headers: cors,
        contentType: 'application/json',
        body: JSON.stringify(value),
      });
    const authed = request.headers().authorization === `Bearer ${TOKEN}` && this.signedIn;
    if (path === '/v1/health') return reply(200, { ok: true, api: 1 });
    if (path === '/v1/google/config') return reply(200, this.google);
    if (path.startsWith('/v1/me') && !authed) return reply(401, { error: 'signed_out' });
    if (path === '/v1/me' && method === 'GET') return reply(200, { user: this.user() });
    if (path === '/v1/me/notify')
      return reply(200, {
        settings: {
          status: true,
          chance: true,
          threshold: 50,
          night_before: false,
          night_time: '20:00',
          quiet_from: '22:00',
          quiet_to: '05:00',
        },
        devices: 0,
      });
    if (path === '/v1/me/trips' && method === 'GET') return reply(200, { trips: this.trips });
    if (path === '/v1/me/trips' && method === 'POST') {
      const sent = body as Omit<
        StubTrip,
        'id' | 'ticket_asked' | 'need_by' | 'ticket' | 'source'
      > & {
        ticket?: StubTrip['ticket'];
        source?: StubTrip['source'];
      };
      const trip: StubTrip = {
        id: String(this.next++).padStart(32, '0'),
        need_by: null,
        ...sent,
        source: sent.source ?? 'typed',
        ticket: sent.ticket ?? 'unsure',
        ticket_asked: sent.ticket !== undefined,
      };
      this.trips.push(trip);
      return reply(201, { trip });
    }
    const one = /^\/v1\/me\/trips\/([0-9a-f]{32})$/.exec(path)?.[1];
    if (one !== undefined) {
      const trip = this.trips.find((t) => t.id === one);
      if (trip === undefined) return reply(404, { error: 'not_found' });
      if (method === 'DELETE') {
        this.trips = this.trips.filter((t) => t.id !== one);
        return reply(200, { ok: true });
      }
      const change = body as Partial<StubTrip>;
      Object.assign(trip, change, { ticket_asked: true });
      return reply(200, { trip });
    }
    if (path === '/v1/me/flights/notify') {
      if (method === 'PATCH') Object.assign(this.flights, body);
      return reply(200, { settings: this.flights });
    }
    if (path === '/v1/me/google')
      return reply(
        200,
        this.google.configured
          ? this.connected
            ? {
                configured: true,
                connected: true,
                email: 'pat@example.com',
                calendar: true,
                send: true,
                since: this.since,
              }
            : { configured: true, connected: false }
          : { configured: false, connected: false },
      );
    if (path === '/v1/me/google/calendar') return reply(200, { events: this.events });
    if (path === '/v1/me/google/finish') {
      if (this.finishRefused) {
        this.connected = false;
        return reply(502, { error: 'google_scopes' });
      }
      this.connected = true;
      this.since = Date.UTC(2026, 0, 9, 18);
      return reply(200, {
        configured: true,
        connected: true,
        email: 'pat@example.com',
        calendar: true,
        send: true,
        since: this.since,
      });
    }
    if (path === '/v1/me/google/start')
      return reply(200, { url: 'https://accounts.google.com/o/oauth2/v2/auth?state=made-up' });
    return reply(404, { error: 'not_found' });
  }
}

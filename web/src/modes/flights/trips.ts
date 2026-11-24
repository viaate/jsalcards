/**
 * Flights trips over the accounts API (api/src/trips.ts, api/src/google.ts): the signed-in
 * account's saved flights, its Flights alert choices, and Connect Google. Every call carries the
 * account's session; a call that comes back signed out ends the session as the account code does.
 */
import { ApiError, type Api } from '../../account/api';
import type { AccountStore } from '../../account/session';
import type { TicketKey } from '../../copy-trips';
import type { CalendarEvent } from './found';

export interface Trip {
  readonly id: string;
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  readonly day: string;
  readonly leaves: number;
  readonly lands: number;
  readonly ticket: TicketKey;
  readonly ticket_asked: boolean;
  readonly need_by: string | null;
  readonly source: 'typed' | 'calendar' | 'gmail';
}

export type NewTrip = Pick<
  Trip,
  'carrier' | 'number' | 'from' | 'to' | 'day' | 'leaves' | 'lands'
> & {
  readonly ticket?: TicketKey;
  readonly source?: Trip['source'];
};

export interface TripChange {
  readonly ticket?: TicketKey;
  readonly ticket_asked?: true;
  readonly need_by?: string | null;
}

export interface FlightsNotify {
  readonly alerts: boolean;
  readonly threshold: 30 | 50 | 70;
  readonly night_before: boolean;
  readonly night_time: string;
  readonly email: boolean;
}

export interface GoogleConfig {
  readonly configured: boolean;
  readonly client_id: string | null;
  readonly gmail_demo: boolean;
  /** The Gmail demo's own client (its own Google Cloud project), never Connect Google's. */
  readonly gmail_client_id: string | null;
}

export interface GoogleState {
  readonly configured: boolean;
  readonly connected: boolean;
  readonly email?: string;
  readonly calendar?: boolean;
  readonly send?: boolean;
  /** When it was connected (ms since 1970). */
  readonly since?: number;
}

export interface TripsClient {
  list(): Promise<Trip[]>;
  add(trip: NewTrip): Promise<Trip>;
  change(id: string, change: TripChange): Promise<Trip>;
  remove(id: string): Promise<void>;
  notify(): Promise<FlightsNotify>;
  setNotify(change: Partial<FlightsNotify>): Promise<FlightsNotify>;
  googleConfig(): Promise<GoogleConfig>;
  google(): Promise<GoogleState>;
  /** Google's sign-in address; `base`: the site's base path, where /google.html is. */
  startGoogle(base: string): Promise<string>;
  finishGoogle(code: string, state: string): Promise<GoogleState>;
  calendar(): Promise<CalendarEvent[]>;
  disconnectGoogle(): Promise<void>;
}

/** Google is off for this build's API: the page shows no Google option (D12, dormant). */
export const GOOGLE_OFF: GoogleConfig = Object.freeze({
  configured: false,
  client_id: null,
  gmail_demo: false,
  gmail_client_id: null,
});

/** A time (ms) as the day on this device's clock ("2026-11-24"), or null. */
export function localDay(at: number | undefined): string | null {
  if (at === undefined || !Number.isFinite(at)) return null;
  const date = new Date(at);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function createTripsClient(store: AccountStore): TripsClient {
  const api: Api = store.api;
  const call = async <T>(method: string, path: string, body?: unknown): Promise<T> => {
    try {
      return await api.call<T>(method, path, body, store.token());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) store.signedOut();
      throw error;
    }
  };
  return {
    list: async () => (await call<{ trips: Trip[] }>('GET', '/v1/me/trips')).trips,
    add: async (trip) => (await call<{ trip: Trip }>('POST', '/v1/me/trips', trip)).trip,
    change: async (id, change) =>
      (await call<{ trip: Trip }>('PATCH', `/v1/me/trips/${encodeURIComponent(id)}`, change)).trip,
    remove: async (id) => {
      await call('DELETE', `/v1/me/trips/${encodeURIComponent(id)}`);
    },
    notify: async () =>
      (await call<{ settings: FlightsNotify }>('GET', '/v1/me/flights/notify')).settings,
    setNotify: async (change) =>
      (await call<{ settings: FlightsNotify }>('PATCH', '/v1/me/flights/notify', change)).settings,
    // The config is public: any failure reads as Google off, so nothing about Google shows.
    googleConfig: async () => {
      try {
        const config = await api.call<GoogleConfig>('GET', '/v1/google/config');
        if (!config.configured) return GOOGLE_OFF;
        // The demo shows only with a client of its own, never Connect Google's (gmail-read.ts).
        const demo =
          config.gmail_demo &&
          typeof config.gmail_client_id === 'string' &&
          config.gmail_client_id !== '' &&
          config.gmail_client_id !== config.client_id;
        return {
          ...config,
          gmail_demo: demo,
          gmail_client_id: demo ? config.gmail_client_id : null,
        };
      } catch {
        return GOOGLE_OFF;
      }
    },
    google: () => call<GoogleState>('GET', '/v1/me/google'),
    startGoogle: async (base) =>
      (await call<{ url: string }>('POST', '/v1/me/google/start', { base })).url,
    finishGoogle: (code, state) =>
      call<GoogleState>('POST', '/v1/me/google/finish', { code, state }),
    calendar: async () =>
      (await call<{ events: CalendarEvent[] }>('POST', '/v1/me/google/calendar', {})).events,
    disconnectGoogle: async () => {
      await call('DELETE', '/v1/me/google');
    },
  };
}

/** Where /google.html leaves Google's answer for the trips page (session storage, this tab). */
export const GOOGLE_RETURN_KEY = 'snowlight:google-return';

export interface GoogleReturn {
  readonly code: string | null;
  readonly state: string | null;
  readonly error: string | null;
}

/** Google's answer /google.html kept, taken once; null when there is none. */
export function takeGoogleReturn(
  storage: Pick<Storage, 'getItem' | 'removeItem'> | null,
): GoogleReturn | null {
  try {
    const raw = storage?.getItem(GOOGLE_RETURN_KEY) ?? null;
    if (raw === null) return null;
    storage?.removeItem(GOOGLE_RETURN_KEY);
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return null;
    const read = (key: string): string | null => {
      const field = (value as Record<string, unknown>)[key];
      return typeof field === 'string' && field.length > 0 && field.length <= 512 ? field : null;
    };
    return { code: read('code'), state: read('state'), error: read('error') };
  } catch {
    return null;
  }
}

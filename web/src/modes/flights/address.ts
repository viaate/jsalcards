/**
 * What Flights mode shows, and its address, so every screen has a link of its own (flights spec
 * D2): `?mode=flights&airport=MCI`, `&route=MCI-LAX`, `&flight=WN1234-MCI` (the flight and the
 * airport it leaves from), `&day=1` (tomorrow, for a route or a flight), `&storm=MCI-2025-01-05`
 * and `&page=storms` or `&page=record`. Parameters other modes own are kept as they are.
 */

export type FlightsView =
  | { readonly kind: 'home' }
  | { readonly kind: 'airport'; readonly code: string }
  | { readonly kind: 'route'; readonly from: string; readonly to: string; readonly day: number }
  | {
      readonly kind: 'flight';
      readonly carrier: string;
      readonly number: number;
      readonly from: string;
      readonly day: number;
    }
  | { readonly kind: 'storms' }
  | { readonly kind: 'storm'; readonly id: string }
  | { readonly kind: 'record' };

export const FLIGHTS_PARAMS = ['airport', 'route', 'flight', 'day', 'storm', 'page'] as const;

const CODE = /^[A-Z0-9]{3}$/;
const ROUTE = /^([A-Z0-9]{3})-([A-Z0-9]{3})$/;
const FLIGHT = /^([A-Z0-9]{2})(\d{1,4})-([A-Z0-9]{3})$/;
const STORM = /^[A-Z0-9]{3}-\d{4}-\d{2}-\d{2}$/;

function dayOf(params: URLSearchParams): number {
  const day = Number(params.get('day') ?? '0');
  // 3: a flight that leaves after midnight at the end of the third day's night (Best time to fly).
  return day === 1 || day === 2 || day === 3 ? day : 0;
}

export function viewOfSearch(search: string): FlightsView {
  const params = new URLSearchParams(search);
  const airport = params.get('airport')?.toUpperCase() ?? null;
  const route = ROUTE.exec(params.get('route')?.toUpperCase() ?? '');
  const flight = FLIGHT.exec(params.get('flight')?.toUpperCase() ?? '');
  const storm = params.get('storm')?.toUpperCase() ?? null;
  const page = params.get('page');
  if (flight !== null)
    return {
      kind: 'flight',
      carrier: flight[1] ?? '',
      number: Number(flight[2]),
      from: flight[3] ?? '',
      day: dayOf(params),
    };
  if (route !== null && route[1] !== route[2])
    return { kind: 'route', from: route[1] ?? '', to: route[2] ?? '', day: dayOf(params) };
  if (airport !== null && CODE.test(airport)) return { kind: 'airport', code: airport };
  if (storm !== null && STORM.test(storm)) return { kind: 'storm', id: storm };
  if (page === 'storms') return { kind: 'storms' };
  if (page === 'record') return { kind: 'record' };
  return { kind: 'home' };
}

/** `href` showing `view`: Flights' own parameters set for it, every other kept. */
export function hrefOfView(href: string, view: FlightsView): string {
  const url = new URL(href);
  for (const name of FLIGHTS_PARAMS) url.searchParams.delete(name);
  switch (view.kind) {
    case 'airport':
      url.searchParams.set('airport', view.code);
      break;
    case 'route':
      url.searchParams.set('route', `${view.from}-${view.to}`);
      if (view.day > 0) url.searchParams.set('day', String(view.day));
      break;
    case 'flight':
      url.searchParams.set('flight', `${view.carrier}${String(view.number)}-${view.from}`);
      if (view.day > 0) url.searchParams.set('day', String(view.day));
      break;
    case 'storm':
      url.searchParams.set('storm', view.id);
      break;
    case 'storms':
      url.searchParams.set('page', 'storms');
      break;
    case 'record':
      url.searchParams.set('page', 'record');
      break;
    case 'home':
      break;
  }
  return url.href;
}

export function sameView(a: FlightsView, b: FlightsView): boolean {
  return hrefOfView('https://x.invalid/', a) === hrefOfView('https://x.invalid/', b);
}

/** A route's grid cell and the row of its flights that a flight was opened from. */
export interface BackCell {
  readonly day: number;
  readonly block: number;
  readonly row: number;
}

/**
 * The history entry's state for a route that a flight was opened from, and for that flight
 * (TRAV-R13-S2): the cell and row, so Back, a phone's back gesture and Close all come back to the
 * cell picked, as one entry.
 */
export function backState(state: unknown, back: BackCell): Record<string, unknown> {
  const own = typeof state === 'object' && state !== null ? state : {};
  return { ...own, flightsBack: { day: back.day, block: back.block, row: back.row } };
}

/** The cell and row a history entry's state keeps (backState), or null for none or a bad one. */
export function backOf(state: unknown): BackCell | null {
  if (typeof state !== 'object' || state === null) return null;
  const back = (state as { flightsBack?: unknown }).flightsBack;
  if (typeof back !== 'object' || back === null) return null;
  const { day, block, row } = back as Record<string, unknown>;
  const whole = (value: unknown, max: number): value is number =>
    typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max;
  return whole(day, 3) && whole(block, 4) && whole(row, 999) ? { day, block, row } : null;
}

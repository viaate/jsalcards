/**
 * Flights found in the person's own calendar or email (flights spec D12, D19), matched to the
 * usual flights (D11) so the route and times come from the published files, never guessed: a
 * flight number with more than one leg that day asks which leg (one tap), and one that does not
 * match is said so and cannot be added. Nothing found here is saved until the person confirms
 * it, and then only the trip's fields, as typing them does.
 */
import { flightsCopy } from '../../copy-flights';
import type { TicketKey } from '../../copy-trips';
import type { FlightsRoutes, FlightsUsualFlight, LocalDate } from '../../types/generated';
import { localParts, weekdayIndex } from './chance';
import type { Airport } from './data';

/** A flight read from a calendar event or an email, before it is matched. */
export interface FoundFlight {
  readonly carrier: string;
  readonly number: number;
  /** The airport it leaves from, when the event or email names one we cover. */
  readonly from: string | null;
  readonly to: string | null;
  /** The local date it leaves (the departure airport's clock), when known. */
  readonly day: LocalDate | null;
  /** The local minute it leaves, when the event or email says. */
  readonly minute: number | null;
  readonly ticket: TicketKey;
  readonly source: 'calendar' | 'gmail';
}

export interface MatchedTrip {
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  readonly day: LocalDate;
  readonly leaves: number;
  readonly lands: number;
  readonly ticket: TicketKey;
  readonly source: 'calendar' | 'gmail' | 'typed';
}

export type Match =
  | { readonly state: 'matched'; readonly trip: MatchedTrip }
  | { readonly state: 'pick'; readonly options: readonly MatchedTrip[] }
  | { readonly state: 'none'; readonly found: FoundFlight };

const AIRLINES: ReadonlySet<string> = new Set(Object.keys(flightsCopy.airlines));

function fliesOn(row: FlightsUsualFlight, day: LocalDate): boolean {
  return (row.weekdays & (1 << weekdayIndex(day))) !== 0;
}

/**
 * The trip a found flight is: its rows in the newest month it flew from its airport that fly
 * that weekday. One leg (or the one that lands where the email says, or leaves when the event
 * says, within an hour): matched. More than one: the person picks. None: not matched.
 */
export function matchFound(found: FoundFlight, routes: FlightsRoutes | null): Match {
  if (found.from === null || found.day === null || routes === null) return { state: 'none', found };
  const day = found.day;
  let rows: FlightsUsualFlight[] = [];
  for (const month of routes.months) {
    rows = month.flights.filter(
      (row) => row.carrier === found.carrier && row.number === found.number && fliesOn(row, day),
    );
    if (rows.length > 0) break;
  }
  const trips = rows.map((row): MatchedTrip => ({
    carrier: row.carrier,
    number: row.number,
    from: found.from ?? '',
    to: row.to_airport,
    day,
    leaves: row.leaves,
    lands: row.lands,
    ticket: found.ticket,
    source: found.source,
  }));
  const legs = [...new Map(trips.map((trip) => [trip.to, trip])).values()];
  if (legs.length === 0) return { state: 'none', found };
  const byEnd = found.to === null ? [] : legs.filter((trip) => trip.to === found.to);
  if (byEnd.length === 1 && byEnd[0] !== undefined) return { state: 'matched', trip: byEnd[0] };
  const minute = found.minute;
  const byTime = minute === null ? [] : legs.filter((trip) => Math.abs(trip.leaves - minute) <= 60);
  if (byTime.length === 1 && byTime[0] !== undefined) return { state: 'matched', trip: byTime[0] };
  if (legs.length === 1 && legs[0] !== undefined) return { state: 'matched', trip: legs[0] };
  return { state: 'pick', options: legs };
}

// Calendar events (the API's POST /v1/me/google/calendar) --------------------------------------

export interface CalendarEvent {
  readonly summary: string;
  readonly location: string;
  readonly description: string;
  readonly start: string | null;
  readonly start_day: string | null;
  readonly zone: string | null;
  readonly end: string | null;
}

const FLIGHT_NUMBER = /\b([A-Z][A-Z0-9]|[0-9][A-Z])\s?(\d{1,4})\b/g;
const CODE = /\b([A-Z]{3})\b/g;

/** The first airline code and number in `text` that names an airline we know. */
function flightIn(text: string): { carrier: string; number: number } | null {
  for (const match of text.matchAll(FLIGHT_NUMBER)) {
    const carrier = match[1] ?? '';
    const number = Number(match[2]);
    if (AIRLINES.has(carrier) && number >= 1 && number <= 9999) return { carrier, number };
  }
  return null;
}

/** The covered airport codes in `text`, in the order they come. */
function codesIn(text: string, airports: ReadonlyMap<string, Airport>): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(CODE)) {
    const code = match[1] ?? '';
    if (airports.has(code) && !out.includes(code)) out.push(code);
  }
  return out;
}

/**
 * A calendar event as a found flight, or null when it names no flight. The airport it leaves
 * from: the first covered code in its place, else in its title or notes ("Flight to Los Angeles
 * (WN 1234)" in Kansas City MCI); the other end: the next code. Its local date and time come
 * from the event's start at that airport's clock.
 */
export function fromCalendar(
  event: CalendarEvent,
  airports: ReadonlyMap<string, Airport>,
): FoundFlight | null {
  const flight = flightIn(`${event.summary} ${event.description}`);
  if (flight === null) return null;
  const place = codesIn(event.location, airports);
  const other = codesIn(`${event.summary} ${event.description}`, airports);
  const codes = [...place, ...other.filter((code) => !place.includes(code))];
  const from = codes[0] ?? null;
  const to = codes.find((code) => code !== from) ?? null;
  let day: string | null = event.start_day;
  let minute: number | null = null;
  const zone = from === null ? null : (airports.get(from)?.tz ?? null);
  if (event.start !== null) {
    const at = Date.parse(event.start);
    if (Number.isFinite(at) && zone !== null) {
      const local = localParts(new Date(at), zone);
      day = local.day;
      minute = local.minute;
    } else if (Number.isFinite(at)) day = null;
  }
  if (day !== null && !/^\d{4}-\d{2}-\d{2}$/.test(day)) day = null;
  return { ...flight, from, to, day, minute, ticket: 'unsure', source: 'calendar' };
}

/**
 * Flights mode's search (flights spec D2's search provider): an airport by its code, city or
 * name; a route ("MCI to LAX", "MCI LAX", "Kansas City to Denver"); a flight ("WN 1234", with
 * the airport it leaves from, typed after it or the one open). Everything is found in the
 * airports table the page already has: nothing is asked of the network while typing.
 */
import { flightsCopy } from '../../copy-flights';
import type { Airport } from './data';

export type FlightsHit =
  | { readonly kind: 'airport'; readonly code: string }
  | { readonly kind: 'route'; readonly from: string; readonly to: string }
  | {
      readonly kind: 'flight';
      readonly carrier: string;
      readonly number: number;
      readonly from: string | null;
    };

export interface FlightsOption {
  readonly id: string;
  readonly hit: FlightsHit;
}

const FLIGHT = /^([A-Z][A-Z0-9]|[0-9][A-Z])\s*(\d{1,4})(?:\s+(?:FROM\s+)?([A-Z0-9]{3}))?$/;
const SPLIT = /\s+(?:TO|-)\s+|\s*(?:->|→|–|—|>)\s*|\s*-\s*(?=[A-Z0-9]{3}$)/;

function normal(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9 >\-–—→]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Airlines by the names people say ("SOUTHWEST"), to their codes, for "Southwest 2510". */
const AIRLINE_CODES: ReadonlyMap<string, string> = new Map(
  Object.entries(flightsCopy.airlines).map(([code, name]) => [normal(name), code]),
);
const NAMED_FLIGHT = /^([A-Z][A-Z ]*?)\s*(?:AIRLINES?|AIRWAYS)?\s+(\d{1,4})(\b.*)$/;

/** "SOUTHWEST 2510 MCI" as "WN 2510 MCI": an airline's name before a number, as its code. */
function withCode(query: string): string {
  const named = NAMED_FLIGHT.exec(query);
  const code = named === null ? undefined : AIRLINE_CODES.get((named[1] ?? '').trim());
  return code === undefined || named === null
    ? query
    : `${code} ${named[2] ?? ''}${named[3] ?? ''}`;
}

/** How well `airport` answers `text` (normalized); 0 is no match. Its code first, then city, then name. */
function score(airport: Airport, text: string): number {
  if (text === '') return 0;
  if (airport.code === text) return 100;
  const city = normal(airport.city);
  const name = normal(airport.name);
  if (city === text) return 80 + Math.min(airport.perDay, 1000) / 100;
  if (city.startsWith(text)) return 60 + Math.min(airport.perDay, 1000) / 100;
  if (text.length >= 2 && airport.code.startsWith(text)) return 50;
  if (
    name.split(' ').some((word) => word.startsWith(text)) ||
    (text.includes(' ') && name.includes(text))
  )
    return 40 + Math.min(airport.perDay, 1000) / 100;
  return 0;
}

/** The airports that answer `text`, best first. */
export function findAirports(airports: readonly Airport[], text: string, limit = 5): Airport[] {
  const query = normal(text);
  return airports
    .map((airport) => ({ airport, score: score(airport, query) }))
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score || b.airport.perDay - a.airport.perDay)
    .slice(0, limit)
    .map((row) => row.airport);
}

/** The one airport `text` names best, or null. */
function bestAirport(airports: readonly Airport[], text: string): Airport | null {
  return findAirports(airports, text, 1)[0] ?? null;
}

/**
 * What `text` can be: a flight first (a carrier code and a number), then a route (two places
 * with "to" between), then airports. `open` is the airport whose panel is open, the one a flight
 * number alone leaves from.
 */
export function searchFlights(
  airports: readonly Airport[],
  text: string,
  open: string | null = null,
  listId = 'flights-results',
): FlightsOption[] {
  const query = normal(text);
  if (query === '') return [];
  const options: FlightsOption[] = [];
  const flight = FLIGHT.exec(withCode(query));
  if (flight !== null) {
    const carrier = flight[1] ?? '';
    const number = Number(flight[2]);
    const named = flight[3] ?? null;
    const from =
      named !== null && airports.some((airport) => airport.code === named) ? named : open;
    options.push({
      id: `${listId}-flight`,
      hit: { kind: 'flight', carrier, number, from },
    });
    return options;
  }
  const parts = query.split(SPLIT).filter((part) => part !== '');
  const pair =
    parts.length === 2 ? parts : /^[A-Z0-9]{3} [A-Z0-9]{3}$/.test(query) ? query.split(' ') : null;
  if (pair !== null) {
    const from = bestAirport(airports, pair[0] ?? '');
    const to = bestAirport(airports, pair[1] ?? '');
    if (from !== null && to !== null && from.code !== to.code) {
      options.push({
        id: `${listId}-route`,
        hit: { kind: 'route', from: from.code, to: to.code },
      });
    }
  }
  for (const airport of findAirports(airports, query)) {
    options.push({ id: `${listId}-${airport.code}`, hit: { kind: 'airport', code: airport.code } });
  }
  return options;
}

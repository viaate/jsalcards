/**
 * The demo-only Gmail parser (flights spec D19, GOOGLE RULE): it reads airline confirmation
 * emails ON THE DEVICE and sends nothing from them anywhere. Loaded only when the person presses
 * Find my flights in Gmail (FlightsMode: import()), never in the page's first script.
 *
 * First the schema.org FlightReservation markup airlines put in their emails (reservationFor:
 * the flight number, airline, airports and departure time; airplaneSeatClass), then the
 * airline's own fare words from the small checked table below. A word not in the table gives
 * Not sure, and the person gets the one tap. An email with no flight markup is not a trip.
 */
import type { TicketKey } from '../../copy-trips';
import type { FoundFlight } from './found';
import { localParts } from './chance';
import type { Airport } from './data';

/**
 * The fare words each airline uses on its own public pages, and the ticket type each one is.
 * Every row names the page the builder read and the day (Nov 23, 2026). Airlines whose pages a
 * plain request could not read that day (Delta, United, Southwest, Spirit, Frontier) have no
 * rows: their emails give Not sure and the one tap, never a guess. Single common words (Alaska's
 * Main and Premium) are left out too: "Main" is also a street.
 */
export const FARE_WORDS: readonly {
  readonly airline: string;
  readonly words: string;
  readonly ticket: Exclude<TicketKey, 'unsure'>;
  readonly page: string;
  readonly checked: string;
}[] = [
  {
    airline: 'AA',
    words: 'Basic Economy',
    ticket: 'basic',
    page: 'https://www.aa.com/i18n/travel-info/experience/seats/basic-economy.jsp',
    checked: '2026-11-23',
  },
  {
    airline: 'AA',
    words: 'Main Cabin',
    ticket: 'regular',
    page: 'https://www.aa.com/i18n/travel-info/experience/seats/basic-economy.jsp',
    checked: '2026-11-23',
  },
  {
    airline: 'AS',
    words: 'Saver',
    ticket: 'basic',
    page: 'https://www.alaskaair.com/content/travel-info/flight-experience/saver',
    checked: '2026-11-23',
  },
  {
    airline: 'AS',
    words: 'First Class',
    ticket: 'premium',
    page: 'https://www.alaskaair.com/content/travel-info/flight-experience/saver',
    checked: '2026-11-23',
  },
  {
    airline: 'B6',
    words: 'Mint',
    ticket: 'premium',
    page: 'https://www.jetblue.com/flying-with-us/our-fares',
    checked: '2026-11-23',
  },
];

/** The markup's seat classes that are a premium cabin whatever the airline calls its fare. */
const PREMIUM_CABINS = /^(?:first|business|premium economy|premium)(?:\s+class)?$/i;

export interface Email {
  /** The email's HTML (or its text when it has no HTML part). */
  readonly html: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Every JSON-LD object in the email, arrays and @graph opened up. */
function markupOf(html: string): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const blocks = html.matchAll(
    /<script\b[^>]*type\s*=\s*["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi,
  );
  const walk = (value: unknown, depth: number): void => {
    if (depth > 4) return;
    if (Array.isArray(value)) for (const item of value.slice(0, 20)) walk(item, depth + 1);
    else if (isRecord(value)) {
      out.push(value);
      if (Array.isArray(value['@graph'])) walk(value['@graph'], depth + 1);
    }
  };
  for (const block of blocks) {
    try {
      walk(JSON.parse(block[1] ?? ''), 0);
    } catch {
      // Markup that does not read is no flight.
    }
  }
  return out;
}

function typeIs(value: Record<string, unknown>, type: string): boolean {
  const t = value['@type'];
  return t === type || (Array.isArray(t) && t.includes(type));
}

function codeOf(value: unknown): string | null {
  if (!isRecord(value)) return null;
  const code = value.iataCode;
  return typeof code === 'string' && /^[A-Z0-9]{2,3}$/.test(code) ? code : null;
}

/** The email's words, its tags taken off. */
function textOf(html: string): string {
  return html
    .replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ');
}

/** The ticket type an email shows for `airline`: the markup's cabin, then the fare words. */
export function ticketOf(airline: string, seatClass: string | null, text: string): TicketKey {
  if (seatClass !== null && PREMIUM_CABINS.test(seatClass.trim())) return 'premium';
  const hits = new Set<TicketKey>();
  for (const row of FARE_WORDS) {
    if (row.airline !== airline) continue;
    const pattern = new RegExp(`(?<![A-Za-z])${row.words.replace(/[+]/g, '\\+')}(?![A-Za-z])`);
    if (pattern.test(text)) hits.add(row.ticket);
  }
  // "Main" can sit inside "Main Cabin" or next to "Saver" in a fare list: only one plain answer counts.
  if (hits.size === 1) return [...hits][0] ?? 'unsure';
  return 'unsure';
}

/**
 * The flights in one airline confirmation email (one per leg), or none: an email with no
 * FlightReservation markup is not read further.
 */
export function flightsInEmail(
  email: Email,
  airports: ReadonlyMap<string, Airport>,
): FoundFlight[] {
  const reservations = markupOf(email.html).filter((item) => typeIs(item, 'FlightReservation'));
  if (reservations.length === 0) return [];
  const text = textOf(email.html);
  const found: FoundFlight[] = [];
  for (const reservation of reservations) {
    const flight = reservation.reservationFor;
    if (!isRecord(flight)) continue;
    const code = codeOf(flight.airline);
    const carrier = code !== null && /^[A-Z0-9]{2}$/.test(code) ? code : null;
    const raw =
      typeof flight.flightNumber === 'string' || typeof flight.flightNumber === 'number'
        ? String(flight.flightNumber)
        : '';
    const digits = /^(?:(?:[A-Z][A-Z0-9]|[0-9][A-Z])\s?)?(\d{1,4})$/.exec(raw.trim());
    const number = digits === null ? NaN : Number(digits[1]);
    if (carrier === null || !Number.isInteger(number) || number < 1) continue;
    const from = codeOf(flight.departureAirport);
    const to = codeOf(flight.arrivalAirport);
    const fromCovered = from !== null && airports.has(from) ? from : null;
    let day: string | null = null;
    let minute: number | null = null;
    const at = typeof flight.departureTime === 'string' ? Date.parse(flight.departureTime) : NaN;
    const zone = fromCovered === null ? undefined : airports.get(fromCovered)?.tz;
    if (Number.isFinite(at) && zone !== undefined) {
      const local = localParts(new Date(at), zone);
      day = local.day;
      minute = local.minute;
    }
    const ticketed = isRecord(reservation.reservedTicket) ? reservation.reservedTicket : null;
    const seat = isRecord(ticketed?.ticketedSeat) ? ticketed.ticketedSeat : null;
    const seatClass =
      typeof reservation.airplaneSeatClass === 'string'
        ? reservation.airplaneSeatClass
        : isRecord(reservation.airplaneSeatClass) &&
            typeof reservation.airplaneSeatClass.name === 'string'
          ? reservation.airplaneSeatClass.name
          : typeof seat?.seatingType === 'string'
            ? seat.seatingType
            : null;
    const leg: FoundFlight = {
      carrier,
      number,
      from: fromCovered,
      to: to !== null && airports.has(to) ? to : null,
      day,
      minute,
      ticket: ticketOf(carrier, seatClass, text),
      source: 'gmail',
    };
    if (
      !found.some(
        (f) =>
          f.carrier === leg.carrier &&
          f.number === leg.number &&
          f.day === leg.day &&
          f.from === leg.from,
      )
    )
      found.push(leg);
  }
  return found;
}

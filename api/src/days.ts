/**
 * The local days a manual status lists, in the school's own time zone.
 *
 * The admin picks Today, Tomorrow, or Today and tomorrow for the school; the
 * browser sends those dates (YYYY-MM-DD) with the zone, and the Worker checks
 * them against its own clock in that zone. A status ends at the end of its
 * last listed day; a listed day whose end has passed is no longer served.
 *
 * CPU budget (10 ms per request on the free plan): one Intl formatter per zone,
 * kept for the life of the isolate; a few formats per override.
 */

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** An IANA zone name such as America/New_York or America/Indiana/Indianapolis. */
const ZONE = /^[A-Z][A-Za-z]+(?:\/[A-Za-z][A-Za-z0-9_+-]*){1,2}$/;
const DAY_MS = 86_400_000;

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string): Intl.DateTimeFormat {
  let found = formatters.get(zone);
  if (found === undefined) {
    found = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    formatters.set(zone, found);
  }
  return found;
}

function wall(at: number, zone: string): [number, number, number, number, number, number] {
  const parts = formatter(zone).formatToParts(new Date(at));
  const get = (type: string): number => Number(parts.find((p) => p.type === type)?.value ?? '0');
  return [get('year'), get('month'), get('day'), get('hour'), get('minute'), get('second')];
}

/** The zone, when it is a time zone this runtime knows; else null. */
export function timeZone(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 64 || !ZONE.test(value)) return null;
  try {
    formatter(value);
    return value;
  } catch {
    return null;
  }
}

/** The calendar date at `at` in `zone`, as YYYY-MM-DD. */
export function localDate(at: number, zone: string): string {
  const [y, m, d] = wall(at, zone);
  return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

/** The date `days` after `day` (both YYYY-MM-DD). */
export function addDays(day: string, days: number): string {
  const [, y, m, d] = DATE.exec(day)!.map(Number) as [number, number, number, number];
  return new Date(Date.UTC(y, m - 1, d) + days * DAY_MS).toISOString().slice(0, 10);
}

/** A real calendar date written YYYY-MM-DD; else null. */
export function calendarDate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const match = DATE.exec(value);
  if (match === null) return null;
  const [y, m, d] = match.slice(1).map(Number) as [number, number, number];
  const at = new Date(Date.UTC(y, m - 1, d));
  return at.getUTCFullYear() === y && at.getUTCMonth() === m - 1 && at.getUTCDate() === d
    ? value
    : null;
}

/** The instant `day` ends in `zone`: the next day's local midnight. */
export function endOfDay(day: string, zone: string): number {
  const [, y, m, d] = DATE.exec(day)!.map(Number) as [number, number, number, number];
  const target = Date.UTC(y, m - 1, d + 1, 0, 0, 0);
  const offset = (at: number): number => {
    const [yy, mm, dd, hh, mi, ss] = wall(at, zone);
    return Date.UTC(yy, mm - 1, dd, hh, mi, ss) - Math.floor(at / 1000) * 1000;
  };
  let at = target - offset(target);
  // Across a change of clocks the offset at the answer can differ from the guess's.
  at = target - offset(at);
  return at;
}

/**
 * The days a request lists, checked: one or two dates, ascending and next to
 * each other, each the zone's today or tomorrow at `now`. Null otherwise.
 */
export function listedDays(value: unknown, zone: string, now: number): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 2) return null;
  const days: string[] = [];
  for (const item of value) {
    const day = calendarDate(item);
    if (day === null) return null;
    days.push(day);
  }
  const today = localDate(now, zone);
  const allowed = [today, addDays(today, 1)];
  if (!days.every((day) => allowed.includes(day))) return null;
  if (days.length === 2 && (days[0] !== today || days[1] !== allowed[1])) return null;
  return days;
}

/**
 * A stored override's days that have not ended at `now`. A row from before
 * days were stored (null zone) keeps its one day until its expiry.
 */
export function daysLeft(days: readonly string[], zone: string | null, now: number): string[] {
  if (zone === null || timeZone(zone) === null) return [...days];
  return days.filter((day) => endOfDay(day, zone) > now);
}

/** The days column as stored (a JSON array of dates); [] for anything else. */
function parsedDays(text: string | null): string[] {
  if (text === null) return [];
  try {
    const value: unknown = JSON.parse(text);
    if (!Array.isArray(value)) return [];
    const days = value.map(calendarDate);
    return days.every((day): day is string => day !== null) ? days : [];
  } catch {
    return [];
  }
}

/** Twelve hours: every US zone is 4 to 10 hours behind UTC (migration 0002). */
const HALF_DAY_MS = 43_200_000;

/**
 * A stored override's days and zone, as the row holds them when this Worker
 * wrote it: one or two dates whose last one ends at `expires_at` in a known
 * zone. Any other row (days missing, as migration 0002 left them for a row
 * set before days were stored, or a row the Worker before days rewrote after
 * the migration, whose `days` then disagree with its new expiry) keeps one day
 * from its expiry, as the migration gives it: the UTC date of `expires_at` less
 * 12 hours, with no zone (it is then held until `expires_at`).
 */
export function storedDays(
  text: string | null,
  zone: string | null,
  expiresAt: number,
): { days: string[]; time_zone: string | null } {
  const days = parsedDays(text);
  const known = timeZone(zone);
  if (
    known !== null &&
    days.length >= 1 &&
    days.length <= 2 &&
    (days.length === 1 || days[1] === addDays(days[0]!, 1)) &&
    endOfDay(days[days.length - 1]!, known) === expiresAt
  ) {
    return { days, time_zone: known };
  }
  return {
    days: [new Date(expiresAt - HALF_DAY_MS).toISOString().slice(0, 10)],
    time_zone: null,
  };
}

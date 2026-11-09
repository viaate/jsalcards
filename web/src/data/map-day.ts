/**
 * The day the map shows for each school: its MAP DAY, the one rule the glow,
 * its counts, the key's day words and the school panel's today all follow.
 *
 * A school's map day is its own today, in its district's time zone, until
 * 3:30 PM there (MAP_DAY_TURN), and its own tomorrow from then until midnight
 * there; after midnight that same date is its today, so nothing changes at
 * midnight. Most districts post a closing the evening before, so from the end
 * of its school day the map shows the day ahead of it.
 *
 * Its time zone is its district's (a private school's own) as
 * predictions/latest.json gives it (MapZones): a district's clock does not
 * age, so the file's own age is no matter here (the chances it carries go
 * stale, never the zones). A school the file gives no zone keeps the rule
 * from before any zone was known (todayEverywhere): the day that is today in
 * every contiguous US time zone, and none in the hours between.
 */

import type { RegionKey } from '../copy-format';
import { parseInstant } from '../state/instant';
import type { DirectoryStamp, LocalDate, PredictionsFile } from '../types/generated';

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;
/** Eastern Daylight Time, the contiguous US zone furthest ahead of UTC. */
const EAST_OFFSET_HOURS = -4;
/** Pacific Standard Time, the one furthest behind. */
const WEST_OFFSET_HOURS = -8;

/**
 * The zone of a school whose zone cannot be read (a predictions file shipped
 * but not had, or for another directory), in the contiguous US: its map day
 * is the day that is today everywhere (todayEverywhere) while every contiguous
 * US clock's map day is that day too, and none otherwise (from 3:30 PM in the
 * East until the West's morning), so it is the map day of a school the file
 * gives a zone and of one it gives none alike: never a day guessed for it. The school panel then reads its today as the day that is
 * today everywhere (school-day.ts schoolToday), so its words name the day
 * its light shows.
 */
export const UNREAD_ZONE = '*';

/**
 * The zone of a school whose clock cannot be told at all: one outside the
 * contiguous US while the zones cannot be read. It has no day: it lights
 * none, and its panel names none.
 */
export const UNKNOWN_ZONE = '?';

/**
 * The clocks every school in the contiguous US keeps, east to west: the five
 * UNREAD_ZONE agrees on. Every IANA zone in the lower 48 keeps one of their
 * offsets and their rules (Detroit, Indiana, Kentucky, Boise, North Dakota
 * and Menominee alike), so none but these five matters there.
 */
const CONTIGUOUS = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
] as const;

/**
 * Whether a place is in the contiguous US, by a box about it: 24.3 to 49.5
 * degrees north (Key West to the Northwest Angle) and 125 to 66.8 west (Cape
 * Alava to Maine's eastern tip). Alaska, Hawaii and the territories are all
 * outside it, so a school there is never lit by the five clocks' day.
 */
export function inContiguous(lon: number, lat: number): boolean {
  return lat >= 24.3 && lat <= 49.5 && lon >= -125 && lon <= -66.8;
}

/** The states of the contiguous US, and DC, by their postal codes. */
const CONTIGUOUS_STATES = new Set(
  (
    'AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY ' +
    'NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'
  ).split(' '),
);

/**
 * The clock a school's day is told by while the zones cannot be read, by the
 * state its record gives (a panel's own school, whose place it does not hold):
 * UNREAD_ZONE in the contiguous US, as schoolZone tells it by place, and
 * UNKNOWN_ZONE anywhere else.
 */
export function unreadZoneOf(state: string): string {
  return CONTIGUOUS_STATES.has(state) ? UNREAD_ZONE : UNKNOWN_ZONE;
}

/** When a school's map day turns to its tomorrow: 3:30 PM on its own clock (owner decision). */
export const MAP_DAY_TURN = { hour: 15, minute: 30 } as const;
const TURN_MINUTE = MAP_DAY_TURN.hour * 60 + MAP_DAY_TURN.minute;

function utcDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** The calendar day after `day` (YYYY-MM-DD). */
export function nextDay(day: LocalDate): LocalDate {
  return new Date(Date.parse(`${day}T00:00:00Z`) + DAY_MS).toISOString().slice(0, 10);
}

/**
 * The calendar day that is today in every contiguous US time zone at `now`,
 * or null in the hours when the East has reached the next day and the West
 * has not: the day of a school with no time zone known.
 */
export function todayEverywhere(now: Date): LocalDate | null {
  const time = now.getTime();
  if (!Number.isFinite(time)) return null;
  const east = utcDate(time + EAST_OFFSET_HOURS * HOUR_MS);
  const west = utcDate(time + WEST_OFFSET_HOURS * HOUR_MS);
  return east === west ? east : null;
}

const clockFormats = new Map<string, Intl.DateTimeFormat>();

/**
 * The calendar day and the minute of it at `now` on a time zone's clock, as
 * numbers alone (no words: the map's lights read them even where the
 * formatters' code cannot load). An unknown zone throws RangeError.
 */
function wallClock(now: Date, timeZone: string): { day: LocalDate; minute: number } {
  let clock = clockFormats.get(timeZone);
  if (clock === undefined) {
    clock = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: 'numeric',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    clockFormats.set(timeZone, clock);
  }
  const parts = new Map(clock.formatToParts(now).map((part) => [part.type, part.value]));
  const [year, month, day, hour, minute] = ['year', 'month', 'day', 'hour', 'minute'].map(
    (type) => parts.get(type as Intl.DateTimeFormatPartTypes) ?? '',
  );
  if (!/^\d{4}$/.test(year ?? '') || !/^\d{2}$/.test(month ?? '') || !/^\d{2}$/.test(day ?? '')) {
    throw new RangeError('map-day: no calendar day in a formatted date');
  }
  return {
    day: `${year ?? ''}-${month ?? ''}-${day ?? ''}`,
    minute: (Number(hour) % 24) * 60 + Number(minute),
  };
}

/** The calendar day at `now` on a time zone's clock (YYYY-MM-DD); null for a clock not known. */
export function localDay(now: Date, timeZone: string): LocalDate | null {
  if (!Number.isFinite(now.getTime())) return null;
  try {
    return wallClock(now, timeZone).day;
  } catch {
    return null;
  }
}

/**
 * A school's map day at `now`: its today before 3:30 PM on its clock, its
 * tomorrow from then; with no time zone (null), the day that is today
 * everywhere (null overnight); with one that cannot be read (UNREAD_ZONE),
 * the day that is today everywhere while it is every contiguous US clock's
 * map day too (null from 3:30 PM in the East until the West's morning). Null also for UNKNOWN_ZONE, and
 * for a clock this browser cannot read.
 */
export function mapDay(now: Date, timeZone: string | null): LocalDate | null {
  if (timeZone === null) return todayEverywhere(now);
  if (timeZone === UNREAD_ZONE) {
    // Only the day that is today everywhere, and only while every contiguous clock is on it:
    // the map day of a school the file gives a zone and of one it gives none alike (the hours
    // the West is past 3:30 PM and the East not yet at midnight light none), so the school's
    // light never steps back once the zones are read, and its panel's today names it.
    const today = todayEverywhere(now);
    if (today === null) return null;
    return CONTIGUOUS.every((zone) => mapDay(now, zone) === today) ? today : null;
  }
  if (!Number.isFinite(now.getTime())) return null;
  try {
    const { day, minute } = wallClock(now, timeZone);
    return minute >= TURN_MINUTE ? nextDay(day) : day;
  } catch {
    return null;
  }
}

/** The instant a calendar day's minute strikes on a time zone's clock. */
function atWall(day: LocalDate, minute: number, timeZone: string): number {
  const target = Date.parse(`${day}T00:00:00Z`) + minute * MINUTE_MS;
  let at = target;
  // Two steps settle any offset; a third, the rare hour a clock change moves.
  for (let i = 0; i < 3; i++) {
    const wall = wallClock(new Date(at), timeZone);
    at += target - (Date.parse(`${wall.day}T00:00:00Z`) + wall.minute * MINUTE_MS);
  }
  return at;
}

/**
 * The next instant after `now` that what the map shows for a school in this
 * time zone can change: its next 3:30 PM or midnight (the day the key names
 * against the visitor's own, and the fallback's, move at midnight); with no
 * zone, the next hour the day that is today everywhere begins or ends. Null
 * where no clock can be read.
 */
export function nextMapTurn(now: Date, timeZone: string | null): Date | null {
  const time = now.getTime();
  if (!Number.isFinite(time)) return null;
  if (timeZone === UNREAD_ZONE) return nextTurnOf(now, [...CONTIGUOUS, null]);
  if (timeZone === null) {
    // The East reaches the next day at 04:00 UTC, the West at 08:00 UTC.
    const midnight = Date.parse(`${utcDate(time)}T00:00:00Z`);
    const turns = [4, 8, 28].map((hour) => midnight + hour * HOUR_MS);
    const next = turns.find((turn) => turn > time);
    return next === undefined ? null : new Date(next);
  }
  try {
    const { day, minute } = wallClock(now, timeZone);
    const at =
      minute < TURN_MINUTE ? atWall(day, TURN_MINUTE, timeZone) : atWall(nextDay(day), 0, timeZone);
    // A clock that settles on a minute already gone (a clock change at the turn): a minute on.
    return new Date(at > time ? at : time + MINUTE_MS);
  } catch {
    return null;
  }
}

/**
 * Each school's time zone, as predictions/latest.json gives it: its
 * district's, or a private school's own. Read once per file (zonesOf).
 */
export interface MapZones {
  /** The directory the file was written against: a school is its position in that one alone. */
  readonly directory: DirectoryStamp;
  /** The file's generated_at, to tell a newer file. */
  readonly generatedAt: string;
  /** The zones the file names, each once, in the order first named. */
  readonly names: readonly string[];
  /** Each district's zone, as its place in `names`, by district position. */
  readonly district: ReadonlyMap<number, number>;
  /** Each private school's zone, as its place in `names`, by school position. */
  readonly school: ReadonlyMap<number, number>;
}

const read = new WeakMap<PredictionsFile, MapZones>();

/** The zones a predictions file (already checked: parsePredictions) gives, read once per file. */
export function zonesOf(predictions: PredictionsFile): MapZones {
  const known = read.get(predictions);
  if (known !== undefined) return known;
  const names: string[] = [];
  const places = new Map<string, number>();
  const placeOf = (zone: string): number => {
    let place = places.get(zone);
    if (place === undefined) {
      place = names.length;
      names.push(zone);
      places.set(zone, place);
    }
    return place;
  };
  const district = new Map<number, number>();
  for (const entry of predictions.districts) district.set(entry.district, placeOf(entry.time_zone));
  const school = new Map<number, number>();
  const fileZones = predictions.zones ?? [];
  for (const entry of predictions.schools ?? []) {
    const zone = fileZones[entry.zone];
    if (zone !== undefined) school.set(entry.school, placeOf(zone));
  }
  const zones: MapZones = {
    directory: predictions.directory,
    generatedAt: predictions.generated_at,
    names,
    district,
    school,
  };
  read.set(predictions, zones);
  return zones;
}

/** Whether the zones were read against this directory: a school's position means it there alone. */
export function zonesFor(zones: MapZones, directory: DirectoryStamp): boolean {
  const own = zones.directory;
  return (
    own.generated_on === directory.generated_on &&
    own.schools === directory.schools &&
    own.districts === directory.districts
  );
}

/**
 * A school's time zone: its district's (`district`, its position, or -1 for
 * none), else its own entry's; null where the file gives it none.
 */
export function zoneOf(zones: MapZones, school: number, district: number): string | null {
  const place = district >= 0 ? zones.district.get(district) : zones.school.get(school);
  return place === undefined ? null : (zones.names[place] ?? null);
}

/**
 * The zones a school's day is told by: a file's (MapZones, read against the
 * school's directory); null in a build that ships no predictions file (every
 * school by the day that is today everywhere); undefined while none for its
 * directory can be had (UNREAD_ZONE, or UNKNOWN_ZONE outside the contiguous US).
 */
export type ToldZones = MapZones | null | undefined;

/**
 * The clock a school's day is told by, the one rule the map's lights, their
 * counts, the lists of schools beside them and the school panel all follow:
 * its zone from the file (null where the file gives none, or with no file
 * shipped), or while none can be had, UNREAD_ZONE in the contiguous US and
 * UNKNOWN_ZONE outside it (`lon`, `lat`: where the school is).
 */
export function schoolZone(
  told: ToldZones,
  school: number,
  district: number,
  lon: number,
  lat: number,
): string | null {
  if (told === null) return null;
  if (told === undefined) return inContiguous(lon, lat) ? UNREAD_ZONE : UNKNOWN_ZONE;
  return zoneOf(told, school, district);
}

/**
 * The calendar day that is today on a school's clock: its zone's; with none
 * (null), or none that can be read (UNREAD_ZONE), the day that is today
 * everywhere (null overnight); null for UNKNOWN_ZONE.
 */
export function clockToday(now: Date, timeZone: string | null): LocalDate | null {
  if (timeZone === null || timeZone === UNREAD_ZONE) return todayEverywhere(now);
  return localDay(now, timeZone);
}

/** One day the map shows, and the time zones it shows it in (null: the schools with none). */
export interface ShownDay {
  readonly day: LocalDate;
  readonly zones: readonly (string | null)[];
  /**
   * Whether the day is today on every clock it is shown in (clockToday): false
   * once any of them is past 3:30 PM, when it shows that clock's tomorrow.
   */
  readonly today: boolean;
}

/**
 * The days the map shows at `now` for schools in these time zones (null:
 * schools with none), the latest day first, each with its zones in the order
 * given. A zone whose day cannot be had (overnight, with none) shows none.
 */
export function shownDays(now: Date, zones: readonly (string | null)[]): readonly ShownDay[] {
  const days = new Map<LocalDate, (string | null)[]>();
  for (const zone of zones) {
    const day = mapDay(now, zone);
    if (day === null) continue;
    const list = days.get(day) ?? [];
    list.push(zone);
    days.set(day, list);
  }
  return [...days.entries()]
    .sort(([a], [b]) => (a < b ? 1 : a > b ? -1 : 0))
    .map(([day, list]) => ({
      day,
      zones: list,
      today: list.every((zone) => clockToday(now, zone) === day),
    }));
}

/** The earliest next turn (nextMapTurn) of any of these zones; null where none can be read. */
export function nextTurnOf(now: Date, zones: readonly (string | null)[]): Date | null {
  let first: Date | null = null;
  for (const zone of zones) {
    const turn = nextMapTurn(now, zone);
    if (turn !== null && (first === null || turn < first)) first = turn;
  }
  return first;
}

const REGIONS: Readonly<Record<string, RegionKey>> = {
  'America/New_York': 'eastern',
  'America/Detroit': 'eastern',
  'America/Indiana/Indianapolis': 'eastern',
  'America/Indiana/Marengo': 'eastern',
  'America/Indiana/Petersburg': 'eastern',
  'America/Indiana/Vevay': 'eastern',
  'America/Indiana/Vincennes': 'eastern',
  'America/Indiana/Winamac': 'eastern',
  'America/Kentucky/Louisville': 'eastern',
  'America/Kentucky/Monticello': 'eastern',
  'America/Chicago': 'central',
  'America/Indiana/Knox': 'central',
  'America/Indiana/Tell_City': 'central',
  'America/Menominee': 'central',
  'America/North_Dakota/Beulah': 'central',
  'America/North_Dakota/Center': 'central',
  'America/North_Dakota/New_Salem': 'central',
  'America/Denver': 'mountain',
  'America/Boise': 'mountain',
  'America/Phoenix': 'arizona',
  'America/Los_Angeles': 'pacific',
  'America/Anchorage': 'alaska',
  'America/Juneau': 'alaska',
  'America/Metlakatla': 'alaska',
  'America/Nome': 'alaska',
  'America/Sitka': 'alaska',
  'America/Yakutat': 'alaska',
  'Pacific/Honolulu': 'hawaii',
};

/** Where in the country a time zone keeps its clock, for the key's day line; `other` for none. */
export function regionOf(zone: string | null): RegionKey {
  return zone === null ? 'other' : (REGIONS[zone] ?? 'other');
}

// predictions/latest.json -------------------------------------------------------------------
// The file checked against its schema: what the school panel's chance (school-day.ts) and the
// map's zones (above, and live.ts) read it by. Here, apart from the words, so the map's lights
// load and read their zones even where the formatters' code cannot.

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_INDEX = 4_294_967_294;
const REASON_COUNT = 8;

export function isIndex(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= MAX_INDEX;
}

function isProbability(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

/** A chance of no school: never a certainty (0.01 to 0.99), so its sum always shows. */
function isChance(value: unknown): value is number {
  return isProbability(value) && value >= 0.01 && value <= 0.99;
}

const zones = new Map<string, boolean>();

/** An IANA time zone this browser knows: "America/Chicago". */
export function isTimeZone(value: unknown): value is string {
  if (typeof value !== 'string' || value === '') return false;
  let known = zones.get(value);
  if (known === undefined) {
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: value });
      known = true;
    } catch {
      known = false;
    }
    zones.set(value, known);
  }
  return known;
}

export function parseStamp(value: unknown): DirectoryStamp | null {
  if (typeof value !== 'object' || value === null) return null;
  const { generated_on: day, schools, districts } = value as Record<string, unknown>;
  if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
  if (!isIndex(schools) || !isIndex(districts)) return null;
  return { generated_on: day, schools, districts };
}

function parseForecast(value: unknown): boolean {
  if (typeof value !== 'object' || value === null) return false;
  const day = value as Record<string, unknown>;
  switch (day.state) {
    case 'no_threat':
      return true;
    case 'forecast': {
      // Every forecast carries its reasons list, even empty (contract: the one default the
      // compact file keeps).
      const reasons = day.reasons;
      return (
        isChance(day.p_no_school) &&
        isProbability(day.p_delay) &&
        Array.isArray(reasons) &&
        reasons.every(
          (reason) =>
            typeof reason === 'number' &&
            Number.isInteger(reason) &&
            reason >= 0 &&
            reason < REASON_COUNT,
        )
      );
    }
    default:
      return false;
  }
}

/** predictions/latest.json, checked; null for anything else. */
export function parsePredictions(value: unknown): PredictionsFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  if (parseStamp(file.directory) === null) return null;
  const { days, districts } = file;
  if (!Array.isArray(days) || days.length === 0 || !Array.isArray(districts)) return null;
  let previous = '';
  for (const day of days as unknown[]) {
    // Consecutive days, today first.
    if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
    if (previous !== '' && day !== nextDay(previous)) return null;
    previous = day;
  }
  for (const entry of districts as unknown[]) {
    if (typeof entry !== 'object' || entry === null) return null;
    const { district, time_zone: zone, days: forecasts } = entry as Record<string, unknown>;
    if (!isIndex(district) || !Array.isArray(forecasts) || forecasts.length !== days.length) {
      return null;
    }
    if (!isTimeZone(zone)) return null;
    if (!forecasts.every(parseForecast)) return null;
  }
  return parseSchools(file, days.length) ? (value as PredictionsFile) : null;
}

/**
 * The private schools' section (contract C3): each school once, sorted, with its time zone
 * named by its place in the file's zones (each one this browser knows) and one outlook a day
 * named by its place in the file's outlooks, each of which reads. A file without one has no
 * private school's outlook.
 */
function parseSchools(file: Record<string, unknown>, days: number): boolean {
  const schools = file.schools ?? [];
  const outlooks = file.outlooks ?? [];
  const zones = file.zones ?? [];
  if (!Array.isArray(schools) || !Array.isArray(outlooks) || !Array.isArray(zones)) return false;
  if (!outlooks.every(parseForecast) || !zones.every(isTimeZone)) return false;
  let previous = -1;
  for (const entry of schools as unknown[]) {
    if (typeof entry !== 'object' || entry === null) return false;
    const { school, zone, days: named } = entry as Record<string, unknown>;
    if (!isIndex(school) || school <= previous) return false;
    previous = school;
    if (!isIndex(zone) || zone >= zones.length) return false;
    if (!Array.isArray(named) || named.length !== days) return false;
    if (!named.every((index) => isIndex(index) && index < outlooks.length)) return false;
  }
  return true;
}

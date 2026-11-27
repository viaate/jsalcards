/**
 * Reads Flights mode's files (flights spec D7, D10): the live chances from the live host
 * (v1/flights/latest.json and the slot file it names), and the files the monthly job publishes
 * beside them (airports, own records, usual flights, past storms, the track record), and the
 * waivers file (waivers spec W7, W8). Each read is checked for its shape and its time: nothing
 * older than its freshness limit is ever handed on as current.
 */
import { liveRootOf } from '../../pwa/config';
import { dataRootFor } from '../../data/files';
import { clock, clockAt, faaEndedFact, faaFact } from '../../copy-flights';
import type { Fact } from '../../copy-flights';
import { addDays, localParts } from './chance';
import { FlightsProgram } from '../../types/generated';
import type {
  FlightsAirportLive,
  FlightsDayRows,
  FlightsLive,
  FlightsProgramNow,
  FlightsRecord,
  FlightsReplay,
  FlightsReplayIndex,
  FlightsRoutes,
  FlightsTrackRecord,
} from '../../types/generated';

/** A pass runs about every 20 minutes: past 60, three passes have been missed and it is old. */
export const LIVE_FRESH_MINUTES = 60;
/** The FAA's programs are not shown as live past 30 minutes (flights spec D7). */
export const FAA_FRESH_MINUTES = 30;
/** A waivers read past 2 hours says nothing (waivers spec W2, W8). */
export const WAIVERS_FRESH_MINUTES = 120;
/** How often the page looks for a newer pass while Flights shows. */
export const POLL_MS = 5 * 60_000;

export type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

/** The folder the flights files are read from: the live host's, or the site's own data. */
export function flightsRoot(): string {
  const live = liveRootOf(
    import.meta.env.VITE_SNOWLIGHT_LIVE_ROOT,
    import.meta.env.VITE_SNOWLIGHT_LIVE_LOOPBACK === '1',
  );
  return live ?? dataRootFor(import.meta.env.BASE_URL, location.href);
}

/** The airports the site ships (scripts/build-flights-airports.mjs), until the host has its own. */
export function shippedAirportsUrl(): string {
  return new URL(`${import.meta.env.BASE_URL}flights/airports.json`, location.href).href;
}

async function readJson(fetcher: Fetcher, url: string, fresh = false): Promise<unknown> {
  try {
    const response = await fetcher(url, fresh ? { cache: 'no-cache' } : {});
    if (!response.ok) {
      await response.body?.cancel().catch(() => undefined);
      return null;
    }
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInstant(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

function instantOrNull(value: unknown): string | null {
  return isInstant(value) ? value : null;
}

// Airports -----------------------------------------------------------------------------

/** One airport as the page draws it. */
export interface Airport {
  readonly code: string;
  readonly name: string;
  readonly city: string;
  readonly state: string;
  readonly lat: number;
  readonly lon: number;
  readonly tz: string;
  readonly perDay: number;
}

export function readAirports(value: unknown): Airport[] | null {
  if (!isObject(value) || value.schema_version !== 1 || !Array.isArray(value.airports)) return null;
  const airports: Airport[] = [];
  for (const row of value.airports as unknown[]) {
    if (!isObject(row)) continue;
    const { code, name, city, state, lat, lon, tz, per_day: perDay } = row;
    if (
      typeof code !== 'string' ||
      !/^[A-Z0-9]{3}$/.test(code) ||
      typeof name !== 'string' ||
      typeof city !== 'string' ||
      typeof state !== 'string' ||
      typeof lat !== 'number' ||
      typeof lon !== 'number' ||
      typeof tz !== 'string' ||
      typeof perDay !== 'number' ||
      !Number.isFinite(lat) ||
      !Number.isFinite(lon)
    )
      continue;
    airports.push({ code, name, city, state, lat, lon, tz, perDay });
  }
  return airports.length > 0 ? airports : null;
}

// The live chances ---------------------------------------------------------------------

/** The live file as the page reads it, with what its times say about it now. */
export interface LiveRead {
  readonly file: FlightsLive;
  readonly byCode: ReadonlyMap<string, FlightsAirportLive>;
  /** When it was made. */
  readonly at: number;
  /**
   * Whether it is the pass latest.json named when it was read. One that is not (an older slot,
   * a cached copy) is never shown as current; see isStale, which also counts its age.
   */
  readonly named: boolean;
}

/**
 * Whether `read` is old at `now`: past its freshness limit, or not the pass latest.json named.
 * Worked out from the clock at each use, never once at the read: a page that cannot read the
 * file again (no network) turns what it shows gray as it ages, never keeping it as current.
 */
export function isStale(read: LiveRead | null, now: number): boolean {
  return read === null || !read.named || now - read.at > LIVE_FRESH_MINUTES * 60_000;
}

function isBlockRows(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length === 3 &&
    value.every(
      (row) =>
        Array.isArray(row) &&
        row.length === 5 &&
        row.every((v) => v === null || (typeof v === 'number' && v >= 0 && v <= 1000)),
    )
  );
}

function isAirportLive(value: unknown): value is FlightsAirportLive {
  if (!isObject(value)) return false;
  return (
    typeof value.code === 'string' &&
    typeof value.today === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(value.today) &&
    isBlockRows(value.dep_canc) &&
    isBlockRows(value.dep_late) &&
    isBlockRows(value.arr_canc) &&
    isBlockRows(value.arr_late) &&
    Array.isArray(value.rough) &&
    Array.isArray(value.usual) &&
    value.usual.length === 4 &&
    Array.isArray(value.why) &&
    (value.programs === null || Array.isArray(value.programs)) &&
    (value.alerts === null || Array.isArray(value.alerts))
  );
}

/** A slot file checked against the stamp latest.json names (its age is the clock's, isStale). */
export function readLive(latest: unknown, slot: unknown): LiveRead | null {
  if (!isObject(slot) || slot.schema_version !== 1 || !Array.isArray(slot.airports)) return null;
  if (!isInstant(slot.generated_at) || typeof slot.stamp !== 'string') return null;
  const airports = (slot.airports as unknown[]).filter(isAirportLive);
  const file: FlightsLive = {
    schema_version: 1,
    generated_at: slot.generated_at,
    slot: String(slot.slot),
    stamp: slot.stamp,
    run: instantOrNull(slot.run),
    programs_at: instantOrNull(slot.programs_at),
    alerts_at: instantOrNull(slot.alerts_at),
    weather_at: instantOrNull(slot.weather_at),
    observed_at: instantOrNull(slot.observed_at),
    airports,
  };
  const at = Date.parse(file.generated_at);
  const named = isObject(latest) && latest.stamp === file.stamp;
  return {
    file,
    byCode: new Map(airports.map((entry) => [entry.code, entry])),
    at,
    named,
  };
}

/** latest.json, then the slot it names; null when either cannot be read. */
export async function fetchLive(fetcher: Fetcher, root: string): Promise<LiveRead | null> {
  const latest = await readJson(fetcher, new URL('flights/latest.json', root).href, true);
  if (!isObject(latest) || typeof latest.slot !== 'string' || !/^slot-[0-2]$/.test(latest.slot))
    return null;
  const slot = await readJson(
    fetcher,
    new URL(`flights/live/${latest.slot}.json`, root).href,
    true,
  );
  return readLive(latest, slot);
}

/** Whether the FAA part of `read` is live at `now`: read, and no older than its limit. */
export function faaLive(read: LiveRead, now: number): boolean {
  const at = read.file.programs_at;
  if (at === null || isStale(read, now)) return false;
  return now - Date.parse(at) <= FAA_FRESH_MINUTES * 60_000;
}

/**
 * When an FAA program was set to end, as an instant, or null when the FAA gave no end (or one this
 * build cannot read).
 */
export function programEnd(program: FlightsProgramNow): number | null {
  if (program.until === null) return null;
  const at = Date.parse(program.until);
  return Number.isNaN(at) ? null : at;
}

/** Whether an FAA program's stated end has passed by `now`: it is then never said as in place now. */
export function programEnded(program: FlightsProgramNow, now: number): boolean {
  const end = programEnd(program);
  return end !== null && end <= now;
}

/**
 * The one rule for what the FAA says at an airport now (TRAV-R10-B3), shared by the FAA lines, the
 * FAA card and Best time to fly's holds: none unless the read is live (faaLive); the programs still
 * in force first, the gravest first, then those past the end the FAA gave them. One past its end is
 * said as set to end then, never as in place now, and the next read says whether it ended.
 */
export function faaPrograms(
  read: LiveRead | null,
  entry: FlightsAirportLive | null,
  now: number,
): FlightsProgramNow[] {
  if (read === null || entry === null || !faaLive(read, now)) return [];
  const programs = programsBySeverity(entry.programs ?? []);
  return [
    ...programs.filter((program) => !programEnded(program, now)),
    ...programs.filter((program) => programEnded(program, now)),
  ];
}

/** The local clock time in `zone` an FAA program was set to end at, or null with no end given. */
export function programEndClock(program: FlightsProgramNow, zone: string): string | null {
  const end = programEnd(program);
  return end === null ? null : clock(localParts(new Date(end), zone).minute);
}

/** The FAA programs that keep a time from being named the safest: each is named where it is said. */
export const HOLDING: ReadonlySet<number> = new Set([
  FlightsProgram.ground_stop,
  FlightsProgram.ground_delay,
  FlightsProgram.closed,
]);

/**
 * The FAA rows under a Flights answer at `code` (null: the airport the panel names; LR-F9): its
 * gravest program, and one for each other hold (HOLDING: a stop, a ground delay or a closing;
 * TRAV-R13-S3), so no hold the answer's other lines name is missing here, and no lesser program
 * beside a hold; those in force first, the gravest first, each said as a fact of now, with the note that
 * the chance does not count it (LR-F4) where the answer shows one (`counted`); then those past
 * their stated end, said as set to end then (faaPrograms). None with an FAA read older than its
 * limit, so an old stop is never said as now. `zone`: the airport's, for the end's clock time.
 * `own`: that clock is not the panel's, so the time names its airport: "5:00 pm LAX time"
 * (TRAV-R11-S4). `named`: programs the answer above already names at this airport, left out.
 */
export function faaFacts(
  read: LiveRead,
  entry: FlightsAirportLive | null,
  code: string | null,
  zone: string,
  now: number,
  counted = false,
  own = false,
  named: readonly number[] = [],
): Fact[] {
  return faaPrograms(read, entry, now).flatMap((program, index) => {
    if ((index > 0 && !HOLDING.has(program.program)) || named.includes(program.program)) return [];
    const end = programEnded(program, now) ? programEndClock(program, zone) : null;
    const ended = end === null || !own || code === null ? end : clockAt(end, code);
    const fact =
      ended === null
        ? faaFact(program.program, code, counted)
        : faaEndedFact(program.program, code, ended);
    return fact === null ? [] : [fact];
  });
}

/** How grave each FAA program is, by its code: a stop or a closed airport first. */
const PROGRAM_RANK: readonly number[] = [0, 1, 2, 3, 0, 4];

/** The FAA's programs at an airport, the gravest first, so a ground stop is never hidden. */
export function programsBySeverity(programs: readonly FlightsProgramNow[]): FlightsProgramNow[] {
  return [...programs].sort(
    (a, b) => (PROGRAM_RANK[a.program] ?? 9) - (PROGRAM_RANK[b.program] ?? 9),
  );
}

// The monthly files --------------------------------------------------------------------

export function isRecord(value: unknown): value is FlightsRecord {
  return (
    isObject(value) &&
    value.schema_version === 1 &&
    typeof value.code === 'string' &&
    Array.isArray(value.lines) &&
    Array.isArray(value.carriers)
  );
}

export function isRoutes(value: unknown): value is FlightsRoutes {
  return (
    isObject(value) &&
    value.schema_version === 1 &&
    typeof value.code === 'string' &&
    Array.isArray(value.months) &&
    value.months.every(
      (month) => isObject(month) && typeof month.month === 'string' && Array.isArray(month.flights),
    )
  );
}

export function isReplayIndex(value: unknown): value is FlightsReplayIndex {
  return isObject(value) && value.schema_version === 1 && Array.isArray(value.replays);
}

export function isReplay(value: unknown): value is FlightsReplay {
  return (
    isObject(value) &&
    value.schema_version === 1 &&
    typeof value.id === 'string' &&
    Array.isArray(value.said) &&
    Array.isArray(value.departures) &&
    Array.isArray(value.cancelled)
  );
}

export function isTrackRecord(value: unknown): value is FlightsTrackRecord {
  return (
    isObject(value) &&
    value.schema_version === 1 &&
    Array.isArray(value.tests) &&
    Array.isArray(value.months)
  );
}

/** The lead classes the model is tested at (1 to 3: the evening before up to three before). */
const LEADS = [1, 2, 3] as const;
const ALL_LEADS = 0b111;

/**
 * The lead class bits a live day's values come from (the pipeline's features.lead_class): the
 * days from the local date of the day's run at the airport to the day; bit `lead - 1`. With no
 * run or no zone to place it, every lead (the check then asks the record for all three).
 */
function leadBits(entry: FlightsAirportLive, day: number, zone: string | undefined): number {
  const run = entry.runs[day] ?? null;
  if (run === null || zone === undefined) return ALL_LEADS;
  const ran = localParts(new Date(run), zone).day;
  const lead = Math.round(
    (Date.parse(`${addDays(entry.today, day)}T12:00:00Z`) - Date.parse(`${ran}T12:00:00Z`)) /
      86_400_000,
  );
  return LEADS.some((each) => each === lead) ? 1 << (lead - 1) : ALL_LEADS;
}

/**
 * Whether the track record can be for the chances `live` shows (LR-SF2): false where the live
 * file shows a forecast value (its usual bit off) of a target on a day whose lead class the
 * record's gate for that airport and target did not pass, or at an airport the record does not
 * list. The panel's counts are by lead, so a pass at another lead does not cover the day. Such
 * a record is of other chances than the map's, and its counts would contradict the page, so none
 * is shown. `zones`: each airport's time zone, which places its run's date. A usual value where
 * the record passed is no contradiction: the files show the usual rate there too when the
 * airport's observations are not fresh or the day follows a storm (live.py _chance).
 */
export function trackRecordFits(
  record: FlightsTrackRecord,
  live: FlightsLive,
  zones: ReadonlyMap<string, string>,
): boolean {
  const airports: unknown = record.airports;
  if (!Array.isArray(airports)) return false;
  const passed = new Map<string, readonly number[]>();
  for (const gate of record.airports) passed.set(gate.code, gate.passed);
  const rows = (entry: FlightsAirportLive): readonly FlightsDayRows[] => [
    entry.dep_canc,
    entry.dep_late,
    entry.arr_canc,
    entry.arr_late,
  ];
  for (const entry of live.airports) {
    const masks = passed.get(entry.code);
    const zone = zones.get(entry.code);
    const fits = (target: number, day: number): boolean => {
      const bits = leadBits(entry, day, zone);
      return ((masks?.[target] ?? 0) & bits) === bits;
    };
    for (const [target, days] of rows(entry).entries()) {
      for (const [day, row] of days.entries()) {
        const usual = entry.usual[target as 0 | 1 | 2 | 3][day] ?? 0;
        const forecast = row.some((value, block) => value !== null && (usual & (1 << block)) === 0);
        if (forecast && !fits(target, day)) return false;
      }
    }
    for (const [day, value] of entry.rough.entries()) {
      const forecast = value !== null && (entry.rough_usual & (1 << day)) === 0;
      if (forecast && !fits(4, day)) return false;
    }
  }
  return true;
}

// Waivers (waivers spec W3, W7; its schema is the waivers lane's) ----------------------------

export interface WaiverAirline {
  readonly code: string;
  readonly name: string;
  readonly path: string;
  readonly state: 'checked' | 'not_checked';
  readonly readAt: string | null;
}

export interface Waiver {
  readonly airline: string;
  /** The airports it covers; null where the page does not say so plainly. */
  readonly airports: readonly string[] | null;
  readonly allAirports: boolean;
  /** Its travel days; null where the page does not state them plainly. */
  readonly travelFrom: string | null;
  readonly travelTo: string | null;
  /** Days next to the covered ones that the page leaves unclear. */
  readonly unclearDays: readonly string[];
  readonly onPage: boolean;
  /** The airline's own active mark; null where its page has none. */
  readonly active: boolean | null;
  /** When it was last seen on the airline's page. */
  readonly lastSeen: number | null;
}

export interface WaiversRead {
  readonly at: number;
  readonly airlines: ReadonlyMap<string, WaiverAirline>;
  readonly waivers: readonly Waiver[];
}

function dateOrNull(value: unknown): string | null {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

export function readWaivers(value: unknown): WaiversRead | null {
  if (!isObject(value) || value.schema_version !== 1 || !isInstant(value.generated_at)) return null;
  if (!Array.isArray(value.airlines) || !Array.isArray(value.waivers)) return null;
  const airlines = new Map<string, WaiverAirline>();
  for (const row of value.airlines as unknown[]) {
    if (!isObject(row) || typeof row.code !== 'string' || typeof row.name !== 'string') continue;
    airlines.set(row.code, {
      code: row.code,
      name: row.name,
      path: typeof row.path === 'string' ? row.path : '/',
      state: row.state === 'checked' ? 'checked' : 'not_checked',
      readAt: instantOrNull(row.read_at),
    });
  }
  const waivers: Waiver[] = [];
  for (const row of value.waivers as unknown[]) {
    if (!isObject(row) || typeof row.airline !== 'string') continue;
    const seen = instantOrNull(row.last_seen);
    waivers.push({
      airline: row.airline,
      // Anything but a plain list of codes is "not stated plainly", never "covers none".
      airports:
        Array.isArray(row.airports) && row.airports.every((code) => typeof code === 'string')
          ? row.airports
          : null,
      allAirports: row.all_airports === true,
      travelFrom: dateOrNull(row.travel_from),
      travelTo: dateOrNull(row.travel_to),
      unclearDays: Array.isArray(row.unclear_days)
        ? row.unclear_days.filter((day): day is string => typeof day === 'string')
        : [],
      onPage: row.on_page !== false,
      active: typeof row.active === 'boolean' ? row.active : null,
      lastSeen: seen === null ? null : Date.parse(seen),
    });
  }
  return { at: Date.parse(value.generated_at), airlines, waivers };
}

/**
 * One airline's line for one airport and day (waivers spec W2 and its ruling LR-W1): a waiver
 * found, none found, unclear, or not checked; never a guess, and not_checked or unclear never
 * shown as none_found. The same rule as the waivers lane's snowlight/waivers/lookup.py.
 */
export type WaiverState =
  | { readonly state: 'waiver'; readonly airline: string; readonly minutes: number }
  | { readonly state: 'none_found'; readonly airline: string; readonly minutes: number }
  | { readonly state: 'unclear'; readonly airline: string; readonly minutes: number }
  | { readonly state: 'not_checked'; readonly airline: string };

/** Whether a waiver names `airport`: yes, no, or not plainly (null). */
function coversAirport(waiver: Waiver, airport: string): boolean | null {
  if (waiver.allAirports) return true;
  if (waiver.airports === null) return null;
  return waiver.airports.includes(airport);
}

/** Whether a waiver's stated travel days hold `day`: yes, no, or not plainly (null). */
function coversDay(waiver: Waiver, day: string): boolean | null {
  if (waiver.unclearDays.includes(day)) return null;
  if (waiver.travelFrom === null || waiver.travelTo === null) return null;
  return waiver.travelFrom <= day && day <= waiver.travelTo;
}

export function waiverState(
  read: WaiversRead | null,
  airline: string,
  airlineName: string,
  airport: string,
  day: string,
  now: number,
): WaiverState {
  const fresh = WAIVERS_FRESH_MINUTES * 60_000;
  const name = read?.airlines.get(airline)?.name ?? airlineName;
  if (read === null || now - read.at >= fresh) return { state: 'not_checked', airline: name };
  const status = read.airlines.get(airline);
  if (status?.state !== 'checked' || status.readAt === null)
    return { state: 'not_checked', airline: name };
  const minutes = (now - Date.parse(status.readAt)) / 60_000;
  if (minutes * 60_000 >= fresh) return { state: 'not_checked', airline: name };
  let unclear = false;
  let unread = false;
  for (const waiver of read.waivers) {
    if (waiver.airline !== airline || !waiver.onPage || waiver.active === false) continue;
    const where = coversAirport(waiver, airport);
    const when = coversDay(waiver, day);
    if (where === false || when === false) continue;
    if (where === true && when === true) {
      // Seen on the page within the limit: found. Else its source has not been read since.
      if (waiver.lastSeen !== null && now - waiver.lastSeen < fresh)
        return { state: 'waiver', airline: name, minutes };
      unread = true;
    } else unclear = true;
  }
  if (unclear) return { state: 'unclear', airline: name, minutes };
  if (unread) return { state: 'not_checked', airline: name };
  return { state: 'none_found', airline: name, minutes };
}

/**
 * Regional airlines, which fly under a bigger airline's name and number (waivers spec W4). BTS
 * lists their flights under their own code; which bigger airline sold each one is not in the
 * published files yet, so their waiver is never guessed.
 */
export const REGIONAL_AIRLINES: ReadonlySet<string> = new Set([
  '9E',
  'C5',
  'G7',
  'MQ',
  'OH',
  'OO',
  'PT',
  'QX',
  'YV',
  'YX',
  'ZW',
]);

/**
 * The airline sites the waiver lines link to, for the airlines whose travel-alerts page the
 * waivers file names by path. An airline not here gets no link.
 */
export const AIRLINE_SITES: Readonly<Record<string, string>> = Object.freeze({
  AA: 'https://www.aa.com',
  AS: 'https://www.alaskaair.com',
  B6: 'https://www.jetblue.com',
  DL: 'https://www.delta.com',
  F9: 'https://www.flyfrontier.com',
  G4: 'https://www.allegiantair.com',
  HA: 'https://www.hawaiianairlines.com',
  MX: 'https://www.flybreeze.com',
  NK: 'https://www.spirit.com',
  SY: 'https://www.suncountry.com',
  UA: 'https://www.united.com',
  WN: 'https://www.southwest.com',
});

// One reader for the mode, keeping what it read ----------------------------------------------

export interface FlightsFiles {
  readonly root: string;
  live(): Promise<LiveRead | null>;
  airports(): Promise<Airport[] | null>;
  record(code: string): Promise<FlightsRecord | null>;
  routes(code: string): Promise<FlightsRoutes | null>;
  replays(): Promise<FlightsReplayIndex | null>;
  replay(id: string): Promise<FlightsReplay | null>;
  trackRecord(): Promise<FlightsTrackRecord | null>;
  waivers(): Promise<WaiversRead | null>;
}

export function createFlightsFiles(
  fetcher: Fetcher = (url, init) => fetch(url, init),
  root: string = flightsRoot(),
  shipped: string = shippedAirportsUrl(),
): FlightsFiles {
  const kept = new Map<string, Promise<unknown>>();
  const once = <T>(key: string, read: () => Promise<T>): Promise<T> => {
    const had = kept.get(key);
    if (had !== undefined) return had as Promise<T>;
    const next = read().then((value) => {
      // A failed read is tried again the next time it is asked for.
      if (value === null) kept.delete(key);
      return value;
    });
    kept.set(key, next);
    return next;
  };
  const at = (path: string): string => new URL(path, root).href;
  return {
    root,
    live: () => fetchLive(fetcher, root),
    // The site's own copy of the committed table (scripts/build-flights-airports.mjs): places do
    // not change with the day, and the host's copy is published only by the monthly job.
    airports: () => once('airports', async () => readAirports(await readJson(fetcher, shipped))),
    record: (code) =>
      once(`record:${code}`, async () => {
        const value = await readJson(fetcher, at(`flights/records/${code.toLowerCase()}.json`));
        return isRecord(value) ? value : null;
      }),
    routes: (code) =>
      once(`routes:${code}`, async () => {
        const value = await readJson(fetcher, at(`flights/routes/${code.toLowerCase()}.json`));
        return isRoutes(value) ? value : null;
      }),
    replays: () =>
      once('replays', async () => {
        const value = await readJson(fetcher, at('flights/replays/index.json'));
        return isReplayIndex(value) ? value : null;
      }),
    replay: (id) =>
      once(`replay:${id}`, async () => {
        const value = await readJson(fetcher, at(`flights/replays/${id.toLowerCase()}.json`));
        return isReplay(value) ? value : null;
      }),
    trackRecord: () =>
      once('track', async () => {
        const value = await readJson(fetcher, at('flights/track-record.json'));
        return isTrackRecord(value) ? value : null;
      }),
    // Read afresh each time: its age decides what it may say.
    waivers: async () => readWaivers(await readJson(fetcher, at('flights/waivers.json'), true)),
  };
}

/** The waiver lines of one airport's card for one day: each airline's state, grouped (W2). */
export interface AirportWaivers {
  readonly found: readonly WaiverState[];
  readonly unclear: readonly WaiverState[];
  /** The airlines with none found, and the oldest of their reads, in minutes. */
  readonly none: readonly string[];
  readonly noneMinutes: number;
  readonly notChecked: readonly string[];
}

/**
 * Every airline in `codes` (those that usually fly from the airport and that the waivers file
 * lists) in its own state: "none" is said only of the airlines that were read and have none,
 * and every airline that could not be read is named as such.
 */
export function airportWaivers(
  read: WaiversRead | null,
  codes: readonly string[],
  airlineName: (code: string) => string,
  airport: string,
  day: string,
  now: number,
): AirportWaivers {
  const found: WaiverState[] = [];
  const unclear: WaiverState[] = [];
  const none: string[] = [];
  const notChecked: string[] = [];
  let noneMinutes = 0;
  for (const code of codes) {
    const state = waiverState(read, code, airlineName(code), airport, day, now);
    if (state.state === 'waiver') found.push(state);
    else if (state.state === 'unclear') unclear.push(state);
    else if (state.state === 'none_found') {
      none.push(state.airline);
      noneMinutes = Math.max(noneMinutes, state.minutes);
    } else notChecked.push(state.airline);
  }
  return { found, unclear, none, noneMinutes, notChecked };
}

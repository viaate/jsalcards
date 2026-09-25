// Hand-written, not generated: gen-types.mjs leaves this file alone.
//
// It reads every published file the way the site does, against the generated types, and
// `npm run check` compiles it. A schema change that breaks a reader fails there, and every
// expected error in refusals() fails the check if the types stop refusing what they must.
// Nothing imports this file, so it never reaches the bundle.

import { PUBLISHED_PATHS, Reason, Status } from './index';
import type {
  AlertsFile,
  ClosingsDay,
  ClosingsFile,
  CoveredFile,
  DayForecast,
  DirectoryStamp,
  PredictionsFile,
  PublishedDocuments,
  ReplayFile,
  SchoolDirectoryMeta,
  SeasonStats,
  TrackRecord,
} from './index';

/** Fetches one published file, typed by its key. */
export async function load<K extends keyof PublishedDocuments>(
  key: K,
  base: URL,
  replayId = '',
): Promise<PublishedDocuments[K]> {
  const response = await fetch(new URL(PUBLISHED_PATHS[key].replace('{id}', replayId), base));
  return (await response.json()) as PublishedDocuments[K];
}

/** Whether a file's indexes point into the directory that is loaded. */
export function sameDirectory(meta: SchoolDirectoryMeta, stamp: DirectoryStamp): boolean {
  return (
    stamp.generated_on === meta.generated_on &&
    stamp.schools === meta.count &&
    stamp.districts === meta.districts.ids.length
  );
}

/** Whether the live check reached a school, by binary search over the ranges. */
export function covers(covered: CoveredFile, school: number): boolean {
  let low = 0;
  let high = covered.ranges.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const range = covered.ranges[middle];
    if (range === undefined) return false;
    const [first, last] = range;
    if (school < first) high = middle;
    else if (school > last) low = middle + 1;
    else return true;
  }
  return false;
}

/** One day of closings.json, decoded once into arrays the map and the panel can index. */
export interface DecodedDay {
  readonly day: string;
  /** Row i's school index, ascending: ready to upload as a GPU buffer. */
  readonly schools: Uint32Array;
  readonly statuses: Uint8Array;
  /** Row i's position in shifts and clocks, or -1 for a closed or remote row. */
  readonly timeSlots: Int32Array;
  readonly group: ClosingsDay;
}

/** A file whose columns disagree is refused whole, never read with a guessed value. */
function column<T>(values: ArrayLike<T>, row: number): T {
  const value = values[row];
  if (value === undefined) throw new RangeError('closings.json: the columns differ in length');
  return value;
}

/** Turns the gap column back into school indexes and lines the time columns up with rows. */
export function decodeDay(group: ClosingsDay): DecodedDay {
  const rows = group.gaps.length;
  const schools = new Uint32Array(rows);
  const statuses = new Uint8Array(rows);
  const timeSlots = new Int32Array(rows);
  let previous = -1;
  let slot = 0;
  group.gaps.forEach((gap, i) => {
    previous += 1 + gap;
    schools[i] = previous;
    const status = column(group.statuses, i);
    statuses[i] = status;
    const shifted = status === Status.delayed || status === Status.early_dismissal;
    timeSlots[i] = shifted ? slot++ : -1;
  });
  return { day: group.day, schools, statuses, timeSlots, group };
}

/** The row of a school in a decoded day, by binary search, or -1. */
export function rowOf(day: DecodedDay, school: number): number {
  let low = 0;
  let high = day.schools.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    const found = day.schools[middle] ?? 0;
    if (found < school) low = middle + 1;
    else if (found > school) high = middle;
    else return middle;
  }
  return -1;
}

/** Everything the detail panel shows for one school on one day. */
export interface SchoolDay {
  readonly status: Status;
  readonly announcedAt: Date | null;
  readonly reason: Reason | null;
  readonly shiftMinutes: number | null;
  /** The stated opening or dismissal time as H:MM, or null. */
  readonly clock: string | null;
}

/** The start of the UTC minute a MinutesAgo value names. */
export function minuteOf(closings: ClosingsFile, ago: number): Date {
  const generatedMinute = Math.floor(Date.parse(closings.generated_at) / 60_000);
  return new Date((generatedMinute - ago) * 60_000);
}

/** One row of a decoded day, with every column read. */
export function readRow(closings: ClosingsFile, day: DecodedDay, row: number): SchoolDay {
  const { group } = day;
  const slot = column(day.timeSlots, row);
  const ago = column(group.announced, row);
  const minute = slot < 0 ? null : column(group.clocks, slot);
  return {
    status: column(group.statuses, row),
    announcedAt: ago === null ? null : minuteOf(closings, ago),
    reason: column(group.reasons, row),
    shiftMinutes: slot < 0 ? null : column(group.shifts, slot),
    clock:
      minute === null
        ? null
        : `${String(Math.floor(minute / 60))}:${String(minute % 60).padStart(2, '0')}`,
  };
}

/** A school's status on a local day: its row, 'open' only where the live check reached it, or null. */
export function statusOn(
  school: number,
  day: string,
  meta: SchoolDirectoryMeta,
  closings: ClosingsFile,
  covered: CoveredFile,
): SchoolDay | 'open' | null {
  if (!sameDirectory(meta, closings.directory) || closings.generated_at !== covered.generated_at) {
    return null;
  }
  const group = closings.days.find((item) => item.day === day);
  if (group !== undefined) {
    const decoded = decodeDay(group);
    const row = rowOf(decoded, school);
    if (row >= 0) return readRow(closings, decoded, row);
  }
  return covers(covered, school) ? 'open' : null;
}

/** The copy key for a status: every code is handled, and a new one fails to compile. */
export function statusKey(status: Status): 'closed' | 'delayed' | 'remote' | 'early' {
  switch (status) {
    case Status.closed:
      return 'closed';
    case Status.delayed:
      return 'delayed';
    case Status.remote:
      return 'remote';
    case Status.early_dismissal:
      return 'early';
    default: {
      const unreachable: never = status;
      return unreachable;
    }
  }
}

/** How many schools have each status on each day, for the glow's per-status buffers. */
export function countsByStatus(closings: ClosingsFile): Map<string, number[]> {
  return new Map(
    closings.days.map((group) => {
      const counts = [0, 0, 0, 0];
      for (const status of group.statuses) counts[status] = (counts[status] ?? 0) + 1;
      return [group.day, counts];
    }),
  );
}

/** The chance of no school, or null when the file states none. */
export function chanceOfNoSchool(day: DayForecast): number | null {
  switch (day.state) {
    case 'forecast':
      return day.p_no_school;
    case 'no_threat':
    case 'not_enough_data':
      return null;
  }
}

/** The reasons behind a district's first-day forecast, as code names. */
export function reasonNames(predictions: PredictionsFile, district: number): string[] {
  const entry = predictions.districts.find((item) => item.district === district);
  const first = entry?.days[0];
  if (first?.state !== 'forecast') return [];
  const names = Object.keys(Reason) as (keyof typeof Reason)[];
  return first.reasons.map((code) => names.find((name) => Reason[name] === code) ?? '');
}

/** The schools lit in frame k of a replay. */
export function frame(replay: ReplayFile, k: number): number[] {
  return replay.rows
    .filter(([, , first, last]) => first <= k && k <= last)
    .map(([school]) => school);
}

/** The alert outlines as MapLibre-ready rings. */
export function outlines(alerts: AlertsFile): [number, number][][] {
  return alerts.alerts.flatMap((alert) =>
    alert.polygons.flatMap((polygon) =>
      polygon.map((ring) => ring.map(([lon, lat]) => [lon, lat])),
    ),
  ) as [number, number][][];
}

/** Totals that the season file leaves to the reader. */
export function seasonTotal(stats: SeasonStats): number {
  return stats.days.reduce(
    (sum, [, closed, delayed, remote, early]) => sum + closed + delayed + remote + early,
    0,
  );
}

/** The observed rate in each calibration bin, or null for an empty bin. */
export function observedRates(record: TrackRecord): (number | null)[] {
  return (record.leads[0]?.no_school.bins ?? []).map(([, , forecasts, outcomes]) =>
    forecasts === 0 ? null : outcomes / forecasts,
  );
}

/** What the types refuse. Each line must be an error. */
export function refusals(
  closings: ClosingsFile,
  group: ClosingsDay,
  day: DayForecast,
  alerts: AlertsFile,
): unknown[] {
  // @ts-expect-error: 7 is not a status code
  const badStatus: ClosingsDay['statuses'] = [0, 7];
  // @ts-expect-error: announced times are minute counts, not ISO text
  const isoTime: ClosingsDay['announced'] = ['2027-01-12T11:42:00Z'];
  // @ts-expect-error: only format version 1 is read
  const version: ClosingsFile['schema_version'] = 2;
  // @ts-expect-error: closings are grouped by day; there is no flat row list
  const flat: unknown = closings.schools;
  // @ts-expect-error: published files have no source field
  const source: unknown = closings.source;
  // @ts-expect-error: a day group has no link
  const link: unknown = group.url;
  // @ts-expect-error: an alert has no link
  const alertLink: unknown = alerts.alerts[0]?.url;
  // @ts-expect-error: chances exist only in the forecast state
  const chance: unknown = day.p_no_school;
  // @ts-expect-error: columns are read-only
  const push: unknown = group.statuses.push;
  // @ts-expect-error: alerts keep their camelCase wire keys
  const generated: unknown = alerts.generated_at;
  return [badStatus, isoTime, version, flat, source, link, alertLink, chance, push, generated];
}

/**
 * live/season.json (pipeline/snowlight/live/season.py): each school's closed,
 * delayed, remote and early-dismissal days this school year, counted from the
 * final day timelines, for the school panel's season line.
 *
 * The panel says a count only when the file holds it and still speaks for
 * now: a file that is missing, does not read, is for another directory, is
 * emptied (a blank) or stale (its last day counted is older than the last day
 * over everywhere, an hour of grace after it) says nothing, and neither does a
 * school it does not list (no day counted, or a school the map does not
 * cover). The file is read when a panel opens, never with the page, and at
 * most once a SEASON_READ_MS while panels open.
 */

import type { SeasonDays } from '../copy-season';
import { PUBLISHED_PATHS } from '../types/generated';
import type { DirectoryStamp, SeasonFile } from '../types/generated';
import { fetchJson } from './files';
import type { DataFiles } from './files';
import { sameStamp } from './school-day';

export const SEASON_PATH = PUBLISHED_PATHS.liveSeason;

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
/** The far west's lag behind UTC (PST): a day is over everywhere 8 hours after UTC midnight. */
const WEST_BEHIND_MS = 8 * HOUR_MS;
/**
 * How long past its due time a file's last day counted still stands: the
 * pass that moves it on runs every 5 minutes, and an hour leaves room for a
 * few refused passes.
 */
export const SEASON_GRACE_MS = HOUR_MS;
/** How often a panel reads the file again: it changes once a day. */
export const SEASON_READ_MS = 10 * 60_000;
const MAX_INDEX = 4_294_967_294;
const MAX_DAYS = 366;
const LOCAL_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const SCHOOL_YEAR = /^(\d{4})-(\d{4})$/;
const DIGEST = /^[0-9a-f]{64}$/;

function isWhole(value: unknown, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max;
}

/** A real calendar day (YYYY-MM-DD) as its UTC midnight in ms, or null. */
function dayMs(value: unknown): number | null {
  if (typeof value !== 'string') return null;
  const match = LOCAL_DATE.exec(value);
  if (match === null) return null;
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Date(ms).toISOString().slice(0, 10) === value ? ms : null;
}

function isStamp(value: unknown): value is DirectoryStamp {
  if (typeof value !== 'object' || value === null) return false;
  const { generated_on: on, schools, districts } = value as Record<string, unknown>;
  return dayMs(on) !== null && isWhole(schools, MAX_INDEX) && isWhole(districts, MAX_INDEX);
}

function wholes(value: unknown, max: number): value is readonly number[] {
  return Array.isArray(value) && value.every((item) => isWhole(item, max));
}

/** live/season.json, checked as the pipeline writes it; null for anything else. */
export function parseSeason(value: unknown): SeasonFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  const {
    season,
    since,
    through,
    directory,
    content_sha256: content,
    gaps,
    closed,
    delayed,
    remote,
    early_dismissal: early,
  } = file;
  if (file.schema_version !== 1 || typeof season !== 'string' || !isStamp(directory)) return null;
  const year = SCHOOL_YEAR.exec(season);
  if (year === null || Number(year[2]) !== Number(year[1]) + 1) return null;
  const first = dayMs(since);
  const last = dayMs(through);
  const start = Date.UTC(Number(year[1]), 6, 1);
  const end = Date.UTC(Number(year[2]), 5, 30);
  if (first === null || last === null || !(start <= first && first <= last && last <= end)) {
    return null;
  }
  if (content !== null && (typeof content !== 'string' || !DIGEST.test(content))) return null;
  if (!wholes(gaps, MAX_INDEX)) return null;
  const columns = [closed, delayed, remote, early];
  if (!columns.every((column) => wholes(column, MAX_DAYS) && column.length === gaps.length)) {
    return null;
  }
  const [c, d, r, e] = columns as (readonly number[])[];
  const span = Math.round((last - first) / DAY_MS) + 1;
  let school = -1;
  for (let row = 0; row < gaps.length; row += 1) {
    school += (gaps[row] ?? 0) + 1;
    const sum = (c?.[row] ?? 0) + (d?.[row] ?? 0) + (r?.[row] ?? 0) + (e?.[row] ?? 0);
    if (sum < 1 || sum > span) return null;
  }
  if (school >= directory.schools || (content === null && gaps.length > 0)) return null;
  return value as SeasonFile;
}

/** The last day over everywhere at `now` (YYYY-MM-DD): the newest day a file can count. */
export function lastDayOver(now: Date): string {
  const at = now.getTime() - WEST_BEHIND_MS;
  return new Date(Date.UTC(...utcParts(at)) - DAY_MS).toISOString().slice(0, 10);
}

function utcParts(ms: number): [number, number, number] {
  const day = new Date(ms);
  return [day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()];
}

/** What the panel's season line says for one school. */
export interface SchoolSeason {
  readonly days: SeasonDays;
  /** The day counting began, when it is after the school year's first day; else null. */
  readonly since: string | null;
}

/**
 * The school's days this school year, from a checked file, or null when the
 * file is for another directory, emptied or stale at `now`, or does not list
 * the school.
 */
export function schoolSeason(
  file: SeasonFile,
  school: number,
  directory: DirectoryStamp,
  now: Date,
): SchoolSeason | null {
  if (!Number.isFinite(now.getTime())) return null;
  if (file.content_sha256 === null || !sameStamp(file.directory, directory)) return null;
  if (file.through < lastDayOver(new Date(now.getTime() - SEASON_GRACE_MS))) return null;
  let index = -1;
  for (let row = 0; row < file.gaps.length; row += 1) {
    index += (file.gaps[row] ?? 0) + 1;
    if (index > school) return null;
    if (index === school) {
      const days: SeasonDays = {
        closed: file.closed[row] ?? 0,
        delayed: file.delayed[row] ?? 0,
        remote: file.remote[row] ?? 0,
        earlyDismissal: file.early_dismissal[row] ?? 0,
      };
      const yearStart = `${file.season.slice(0, 4)}-07-01`;
      return { days, since: file.since > yearStart ? file.since : null };
    }
  }
  return null;
}

interface Read {
  readonly at: number;
  readonly file: Promise<SeasonFile | null>;
}

const reads = new WeakMap<DataFiles, Read>();

/**
 * The season file, read now or at most SEASON_READ_MS ago (one read for every
 * panel opened in that time); null when this build has none (its live root's
 * or its own), it cannot be read or it does not check.
 */
export function readSeason(
  files: DataFiles,
  now: () => number = Date.now,
): Promise<SeasonFile | null> {
  const last = reads.get(files);
  const at = now();
  if (last !== undefined && at - last.at >= 0 && at - last.at < SEASON_READ_MS) return last.file;
  if (!files.has(SEASON_PATH)) return Promise.resolve(null);
  const file = fetchJson(files, SEASON_PATH, { cache: 'no-cache' }).then(parseSeason, () => null);
  reads.set(files, { at, file });
  return file;
}

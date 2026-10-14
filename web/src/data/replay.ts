/**
 * The storm replays, read for the map: replays/index.json, the days the menu
 * offers, and replays/<day>.json, the schools one past school day lit.
 *
 * A replay is one school day (v1): one frame, a day apart, starting at noon
 * UTC on the day its id names. The day is the id itself, a calendar date,
 * never an instant read in the viewer's zone. A file that breaks that, its
 * schema, or whose stamp names another directory, is not read at all: the
 * replay is not offered, or lights nothing.
 *
 * Loaded only when a replay is asked for, or the menu opens.
 */

import { parseInstant } from '../state/instant';
import type {
  LocalDate,
  ReplayFile,
  ReplayIndex,
  ReplayRow,
  ReplaySummary,
  SchoolId,
  Status,
} from '../types/generated';
import { NOTHING_LIT, litRows } from './closings';
import type { LitSchools } from './closings';
import { sameDirectory } from './directory';
import type { Directory } from './directory';

const DAY_ID = /^\d{4}-\d{2}-\d{2}$/;
const STATE = /^[A-Z]{2}$/;
const MINUTES_PER_DAY = 1440;
const REASON_COUNT = 8;
const MAX_INDEX = 4_294_967_294;
const HOUR_MS = 3_600_000;
/** Hawaii, the US zone furthest behind UTC, with no daylight time: UTC-10 all year. */
const LATEST_OFFSET_HOURS = -10;

function isWhole(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

/** Whether `value` is a real calendar day, YYYY-MM-DD. */
export function isReplayDay(value: unknown): value is LocalDate {
  if (typeof value !== 'string' || !DAY_ID.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}

/**
 * Whether a replay keeps v1's one-day form: one frame, a day long, starting at
 * noon UTC on the day its id names.
 */
function isOneDay(
  replay: Pick<ReplaySummary, 'id' | 'start' | 'step_minutes' | 'frames'>,
): boolean {
  return (
    isReplayDay(replay.id) &&
    replay.frames === 1 &&
    replay.step_minutes === MINUTES_PER_DAY &&
    parseInstant(replay.start) !== null &&
    replay.start === `${replay.id}T12:00:00Z`
  );
}

function parseSummary(value: unknown): ReplaySummary | null {
  if (typeof value !== 'object' || value === null) return null;
  const summary = value as Record<string, unknown>;
  const { id, start, step_minutes, frames, peak_schools, peak_frame, schools, states } = summary;
  if (typeof id !== 'string' || typeof start !== 'string') return null;
  if (!isWhole(step_minutes, 5, MINUTES_PER_DAY) || !isWhole(frames, 1, 4032)) return null;
  if (!isOneDay({ id, start, step_minutes, frames })) return null;
  if (!isWhole(schools, 1, MAX_INDEX) || !isWhole(peak_schools, 1, schools)) return null;
  if (!isWhole(peak_frame, 0, frames - 1)) return null;
  if (!Array.isArray(states) || states.length === 0) return null;
  let previous = '';
  for (const state of states as unknown[]) {
    if (typeof state !== 'string' || !STATE.test(state) || state <= previous) return null;
    previous = state;
  }
  return value as ReplaySummary;
}

/** replays/index.json, checked; null for anything else. */
export function parseReplayIndex(value: unknown): ReplayIndex | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  if (!Array.isArray(file.replays)) return null;
  let previous = '';
  for (const entry of file.replays as unknown[]) {
    const summary = parseSummary(entry);
    // Oldest first, one entry per day.
    if (summary === null || summary.id <= previous) return null;
    previous = summary.id;
  }
  return value as ReplayIndex;
}

function parseRow(value: unknown, frames: number): ReplayRow | null {
  if (!Array.isArray(value) || value.length !== 5) return null;
  const [school, status, first, last, reason] = value as unknown[];
  if (!isWhole(school, 0, MAX_INDEX) || !isWhole(status, 0, 3)) return null;
  if (!isWhole(first, 0, frames - 1) || !isWhole(last, first, frames - 1)) return null;
  if (reason !== null && !isWhole(reason, 0, REASON_COUNT - 1)) return null;
  return value as unknown as ReplayRow;
}

/** replays/<day>.json, checked; null for anything else. */
export function parseReplay(value: unknown): ReplayFile | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  if (file.schema_version !== 1 || parseInstant(file.generated_at) === null) return null;
  const { id, start, step_minutes, frames, directory, rows } = file;
  if (typeof id !== 'string' || typeof start !== 'string') return null;
  if (!isWhole(step_minutes, 5, MINUTES_PER_DAY) || !isWhole(frames, 1, 4032)) return null;
  if (!isOneDay({ id, start, step_minutes, frames })) return null;
  if (typeof directory !== 'object' || directory === null) return null;
  const stamp = directory as Record<string, unknown>;
  if (!isReplayDay(stamp.generated_on)) return null;
  if (!isWhole(stamp.schools, 0, MAX_INDEX) || !isWhole(stamp.districts, 0, MAX_INDEX)) {
    return null;
  }
  if (!Array.isArray(rows)) return null;
  let previous = -1;
  for (const entry of rows as unknown[]) {
    const row = parseRow(entry, frames);
    // Sorted by school, one row each: a day has one frame.
    if (row === null || row[0] <= previous) return null;
    previous = row[0];
  }
  return value as ReplayFile;
}

/** The day a replay shows: its id, a calendar date. */
export function replayDay(replay: Pick<ReplayFile, 'id'>): LocalDate {
  return replay.id;
}

/** The calendar day it is in Hawaii at `now`, the last US zone to reach a day. */
function latestUsDay(now: Date): LocalDate {
  return new Date(now.getTime() + LATEST_OFFSET_HOURS * HOUR_MS).toISOString().slice(0, 10);
}

/**
 * The replays to offer at `now`, newest first: each of one-day form whose
 * day is over everywhere in the US, so none is today or later anywhere.
 */
export function shownReplays(index: ReplayIndex, now: Date): ReplaySummary[] {
  if (!Number.isFinite(now.getTime())) return [];
  const today = latestUsDay(now);
  return index.replays
    .filter((replay) => isOneDay(replay) && replay.id < today)
    .sort((a, b) => (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
}

/** Whether a replay's day is over everywhere in the US at `now`. */
export function isPast(day: LocalDate, now: Date): boolean {
  return Number.isFinite(now.getTime()) && isReplayDay(day) && day < latestUsDay(now);
}

/**
 * The schools a replay lights, at their places in the directory, none of
 * them pulsing in. Nothing when the file is for another directory or names a
 * school past its end.
 */
export function lightReplay(replay: ReplayFile, directory: Directory): LitSchools {
  if (!sameDirectory(directory, replay.directory)) return NOTHING_LIT;
  const count = replay.rows.length;
  if (count === 0) return NOTHING_LIT;
  if ((replay.rows[count - 1]?.[0] ?? 0) >= directory.count) return NOTHING_LIT;
  const schools = new Uint32Array(count);
  const statuses = new Uint8Array(count);
  replay.rows.forEach(([school, status], i) => {
    schools[i] = school;
    statuses[i] = status;
  });
  return litRows(directory, schools, statuses, null, 0);
}

/** A school's status and reason on a replay's day. */
export interface ReplayStatus {
  readonly status: Status;
  readonly reason: number | null;
}

/** A school's status on a replay's day, by its id; null for a school the replay does not light. */
export type ReplayLookup = (school: SchoolId) => ReplayStatus | null;

/**
 * Each school's status on a replay's day, for the panels: null for a school
 * the replay does not light. Answers nothing when the file is for another
 * directory.
 */
export function replayLookup(replay: ReplayFile, directory: Directory): ReplayLookup {
  if (!sameDirectory(directory, replay.directory)) return () => null;
  const bySchool = new Map<number, ReplayStatus>();
  for (const [school, status, , , reason] of replay.rows) {
    bySchool.set(school, { status, reason });
  }
  return (id) => {
    const school = directory.schoolIndex(id);
    return school < 0 ? null : (bySchool.get(school) ?? null);
  };
}

/** A replay on the map, as the panels read it: its day, and each school's status that day. */
export interface ReplayOn {
  readonly day: LocalDate;
  readonly lookup: ReplayLookup;
}

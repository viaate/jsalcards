/**
 * Made-up histories for tests and pictures only. Nothing here is a real reading, and none of
 * it is deployed: the preview server and the tests are its only readers.
 */

import { advance, summarize } from '../../shared/history.ts';
import { CHANCES_DOWN, CHANCES_LATE, CLOSINGS_DOWN, CLOSINGS_LATE } from '../../shared/judge.ts';
import { DAY, PARTS, TICK } from '../../shared/types.ts';
import type {
  DayRow,
  Incident,
  Part,
  Reading,
  Sample,
  State,
  Summary,
} from '../../shared/types.ts';

/** What each part read at a tick, or null: the tick is missing (the checker did not run). */
export type Script = (t: number) => Record<Part, State> | null;

const ALL_OK: Record<Part, State> = { site: 'ok', closings: 'ok', chances: 'ok', accounts: 'ok' };

function reading(s: State, made: number | null): Reading {
  return { s, code: s === 'unknown' ? 0 : 200, ms: 120, made, allow: 0, bytes: null };
}

/** How old a file is when it was last made fresh: the age a working file is given. */
const FRESH = 240;
const LIMITS = {
  closings: { late: CLOSINGS_LATE, down: CLOSINGS_DOWN },
  chances: { late: CHANCES_LATE, down: CHANCES_DOWN },
} as const;

/**
 * When a file part's file was made, for the state the script gives it at `t`: an instant the
 * real judge gives that state for. A file in trouble since `since` was last made just before
 * it, pushed back past the state's threshold, and a late one is kept short of "not working".
 */
function madeFor(part: 'closings' | 'chances', s: State, t: number, since: number): number {
  const { late, down } = LIMITS[part];
  if (s === 'down') return Math.min(since - FRESH, t - down - 60);
  if (s === 'late') return Math.max(Math.min(since - FRESH, t - late - 60), t - down + 60);
  return t - FRESH;
}

/** Runs the real history code over every tick from `first` to `last`. */
export function simulate(first: number, last: number, script: Script): Summary {
  const days = new Map<string, DayRow>();
  /** Since when each file part has been late or down without a working reading between. */
  const since: Partial<Record<Part, number>> = {};
  let incidents: Incident[] = [];
  let latest: Sample | null = null;
  let nextId = 1;
  for (let t = first; t <= last; t += TICK) {
    const states = script(t);
    if (states === null) continue;
    const parts = {} as Record<Part, Reading>;
    for (const part of PARTS) {
      const s = states[part];
      if (part !== 'closings' && part !== 'chances') {
        parts[part] = reading(s, null);
        continue;
      }
      if (s === 'ok') delete since[part];
      else if (s !== 'unknown') since[part] ??= t;
      // A file that could not be read has no time of its own.
      parts[part] = reading(s, s === 'unknown' ? null : madeFor(part, s, t, since[part] ?? t));
    }
    const sample: Sample = { t, parts };
    // The store's side of a tick: only the open incidents matter to the next sample.
    const open = incidents.filter((row) => row.ended === null);
    const stepped = advance(
      { first: latest === null ? null : first, days: [], incidents: open },
      sample,
    );
    for (const row of stepped.add) {
      const was = days.get(`${row.day} ${row.part}`);
      days.set(`${row.day} ${row.part}`, {
        ...row,
        ok: (was?.ok ?? 0) + row.ok,
        late: (was?.late ?? 0) + row.late,
        down: (was?.down ?? 0) + row.down,
      });
    }
    const changed = new Map(stepped.changed.map((row) => [row.id, row]));
    incidents = incidents.map((row) => changed.get(row.id) ?? row);
    for (const row of stepped.opened) {
      incidents.push({ ...row, id: nextId });
      nextId += 1;
    }
    latest = sample;
  }
  if (latest === null) throw new Error('no tick was taken');
  return summarize(latest, first, [...days.values()], incidents);
}

/** The tick at or before a clock in seconds. */
export function tickAt(clock: number): number {
  return Math.floor(clock / TICK) * TICK;
}

/**
 * Sixty days of checks ending at `now`: 30 bars before checks began, the website slow for 40
 * minutes 20 days ago, a closings problem 10 days ago that the readings stopped on for 6 hours,
 * a 25-minute closings outage 3 days ago, and the chances late since 65 minutes ago.
 */
export function history(now: number): Summary {
  const today = Math.floor(now / DAY) * DAY;
  const first = today - 59 * DAY;
  const slowFrom = today - 20 * DAY + 14 * 3600;
  const gapFrom = today - 10 * DAY + 3 * 3600;
  const outFrom = today - 3 * DAY + 11 * 3600 + 600;
  const lateFrom = now - 65 * 60;
  return simulate(first, now, (t) => {
    if (t > gapFrom + 2 * TICK && t < gapFrom + 6 * 3600 + 3 * TICK) return null;
    const states = { ...ALL_OK };
    if (t >= slowFrom && t < slowFrom + 40 * 60) states.site = 'late';
    if (t >= gapFrom && t <= gapFrom + 2 * TICK) states.closings = 'down';
    if (t >= outFrom && t < outFrom + 25 * 60) states.closings = 'down';
    if (t >= lateFrom) states.chances = 'late';
    return states;
  });
}

/** Ninety-five clean days: everything working, every check kept. */
export function allOk(now: number): Summary {
  return simulate(Math.floor(now / DAY) * DAY - 95 * DAY, now, () => ALL_OK);
}

/** The longest copy the page can be asked to hold: three parts down and one late, long problems. */
export function worst(now: number): Summary {
  const today = Math.floor(now / DAY) * DAY;
  const first = today - 70 * DAY;
  return simulate(first, now, (t) => {
    const day = Math.floor((t - first) / DAY);
    if (day % 9 === 4 && t % DAY > 3600 && t % DAY < 80000) return null;
    const states = { ...ALL_OK };
    if (day % 9 === 4 || day % 9 === 5) states.closings = 'late';
    if (day % 7 === 3 && t % DAY < 86100) states.chances = t % DAY < 43200 ? 'down' : 'late';
    if (t >= now - 2 * DAY - 23 * 3600) {
      states.site = 'down';
      states.closings = 'down';
      states.chances = 'down';
      states.accounts = 'late';
    }
    return states;
  });
}

/**
 * Launch day: the checks began two hours ago, everything works, and the chances could not be
 * checked at any tick (their stamp is not on the host yet). No problem has been seen.
 */
export function launch(now: number): Summary {
  return simulate(now - 2 * 3600, now, () => ({ ...ALL_OK, chances: 'unknown' }));
}

export type Made = 'history' | 'ok' | 'first' | 'stale' | 'unreachable' | 'worst' | 'launch';
export const MADE: readonly Made[] = [
  'history',
  'ok',
  'first',
  'stale',
  'unreachable',
  'worst',
  'launch',
];

/** What `/api/status` answers for a made-up state at a clock, or null: it does not answer. */
export function answerOf(
  state: Made,
  clock: number,
): { served: number; summary: Summary | null } | null {
  const served = Math.floor(clock);
  if (state === 'unreachable') return null;
  if (state === 'first') return { served, summary: null };
  if (state === 'ok') return { served, summary: allOk(tickAt(clock)) };
  if (state === 'worst') return { served, summary: worst(tickAt(clock)) };
  if (state === 'launch') return { served, summary: launch(tickAt(clock)) };
  if (state === 'stale') return { served, summary: history(tickAt(clock) - 8 * TICK) };
  return { served, summary: history(tickAt(clock)) };
}

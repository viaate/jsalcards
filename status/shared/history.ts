/** Days, incidents and the summary, from one sample at a time. Pure. */

import { DAY, DAYS_KEPT, PARTS, TICK } from './types.ts';
import type {
  DayRow,
  Incident,
  Part,
  Sample,
  State,
  Summary,
  SummaryIncident,
  SummaryPart,
} from './types.ts';

/** With no known reading for longer than this, an open incident ends where the readings stopped. */
export const GAP_SECONDS = 900;
/** The summary carries this many incidents at most. */
export const INCIDENTS_MAX = 100;

/** The UTC day of an instant, 'YYYY-MM-DD'. */
export function dayOf(t: number): string {
  return new Date(t * 1000).toISOString().slice(0, 10);
}

/** The first second of a UTC day. */
export function dayStart(day: string): number {
  return Date.parse(`${day}T00:00:00Z`) / 1000;
}

/** The first second of the oldest of the 90 days kept at `t`: 89 days before `t`'s UTC day. */
export function windowStart(t: number): number {
  return Math.floor(t / DAY) * DAY - (DAYS_KEPT - 1) * DAY;
}

/** What the store holds before a sample: the window's day rows and its incidents. */
export interface Before {
  /** The first tick ever taken in; null on an empty store. */
  first: number | null;
  days: readonly DayRow[];
  incidents: readonly Incident[];
}

/** What a sample changes in the store. */
export interface Advanced {
  first: number;
  /** What to add to the sample's UTC day, one row a part (all zero for `unknown`). */
  add: DayRow[];
  /** Incidents to insert. */
  opened: Incident[];
  /** Incidents already in the store (an `id` each) to write again. */
  changed: Incident[];
}

/** What a sample changes, and the summary after it. */
export interface Stepped extends Advanced {
  summary: Summary;
}

function counted(s: State): [number, number, number] {
  return [s === 'ok' ? 1 : 0, s === 'late' ? 1 : 0, s === 'down' ? 1 : 0];
}

/** The rows one sample changes: its day's counts and its parts' incidents. */
export function advance(before: Before, sample: Sample): Advanced {
  const t = sample.t;
  const first = before.first ?? t;
  const day = dayOf(t);
  const add: DayRow[] = [];
  const opened: Incident[] = [];
  const changed: Incident[] = [];
  for (const part of PARTS) {
    const s = sample.parts[part].s;
    const [ok, late, down] = counted(s);
    add.push({ day, part, ok, late, down });
    let open: Incident | null = null;
    for (const incident of before.incidents) {
      if (incident.part !== part || incident.ended !== null) continue;
      if (open === null || incident.start > open.start) open = incident;
    }
    // (a) The readings stopped: it ends one tick after its last bad reading.
    if (open !== null && t - open.last > GAP_SECONDS) {
      changed.push({ ...open, ended: open.last + TICK, gap: 1 });
      open = null;
    }
    if (s === 'late' || s === 'down') {
      if (open !== null) {
        const kind = s === 'down' ? 'down' : open.kind;
        changed.push({ ...open, last: t, kind });
      } else {
        opened.push({ id: null, part, kind: s, start: t, last: t, ended: null, gap: 0 });
      }
    } else if (s === 'ok' && open !== null) {
      changed.push({ ...open, ended: t });
    }
  }
  return { first, add, opened, changed };
}

/** Take one sample in: the rows it changes, and the summary once they are written. */
export function step(before: Before, sample: Sample): Stepped {
  const { first, add, opened, changed } = advance(before, sample);
  const replaced = new Set(changed.map((row) => row.id));
  const days = new Map<string, DayRow>();
  for (const row of before.days) days.set(`${row.day} ${row.part}`, row);
  for (const row of add) {
    const was = days.get(`${row.day} ${row.part}`);
    days.set(`${row.day} ${row.part}`, {
      day: row.day,
      part: row.part,
      ok: (was?.ok ?? 0) + row.ok,
      late: (was?.late ?? 0) + row.late,
      down: (was?.down ?? 0) + row.down,
    });
  }
  const incidents = [...before.incidents.filter((i) => !replaced.has(i.id)), ...changed, ...opened];
  const summary = summarize(sample, first, [...days.values()], incidents);
  return { first, add, opened, changed, summary };
}

/** The summary the page draws from: the parts now, 90 days of counts, the window's incidents. */
export function summarize(
  sample: Sample,
  first: number,
  days: readonly DayRow[],
  incidents: readonly Incident[],
): Summary {
  const t = sample.t;
  const start = windowStart(t);
  const parts = {} as Record<Part, SummaryPart>;
  const counts = {} as Record<Part, [number, number, number][]>;
  const found = new Map<string, DayRow>();
  for (const row of days) found.set(`${row.day} ${row.part}`, row);
  for (const part of PARTS) {
    const reading = sample.parts[part];
    const files = part === 'closings' || part === 'chances';
    parts[part] =
      files && reading.made !== null ? { s: reading.s, made: reading.made } : { s: reading.s };
    const bars: [number, number, number][] = [];
    for (let i = 0; i < DAYS_KEPT; i += 1) {
      const row = found.get(`${dayOf(start + i * DAY)} ${part}`);
      bars.push([row?.ok ?? 0, row?.late ?? 0, row?.down ?? 0]);
    }
    counts[part] = bars;
  }
  const listed = incidents
    .filter((i) => i.ended === null || i.ended >= start)
    .sort((a, b) => {
      if ((a.ended === null) !== (b.ended === null)) return a.ended === null ? -1 : 1;
      if (a.start !== b.start) return b.start - a.start;
      return PARTS.indexOf(a.part) - PARTS.indexOf(b.part);
    })
    .slice(0, INCIDENTS_MAX)
    .map((i): SummaryIncident => {
      const row: SummaryIncident = { p: i.part, k: i.kind, s: i.start, e: i.ended, g: i.gap };
      if (i.ended === null) row.l = i.last;
      return row;
    });
  return { v: 1, now: t, first, parts, from: dayOf(start), days: counts, incidents: listed };
}

/**
 * How many ticks of the UTC day starting at `start` fall in `[first, now]`: 288 for a whole day,
 * 0 for a day before checks began or after `now`.
 */
export function expected(start: number, first: number, now: number): number {
  const from = Math.max(start, Math.ceil(first / TICK) * TICK);
  const to = Math.min(start + DAY - TICK, Math.floor(now / TICK) * TICK);
  return to < from ? 0 : Math.floor((to - from) / TICK) + 1;
}

export type BarClass = 'before' | 'none' | 'down' | 'late' | 'ok';

export interface Bar {
  cls: BarClass;
  /** Ticks the day should hold so far, readings it does hold, and the ticks with none. */
  e: number;
  k: number;
  m: number;
}

/** A day's bar. A gap is never drawn as working: under half the day's readings is `none`. */
export function barOf(counts: readonly [number, number, number], e: number): Bar {
  const [ok, late, down] = counts;
  const k = ok + late + down;
  const m = Math.max(0, e - k);
  let cls: BarClass;
  if (e === 0) cls = 'before';
  else if (k === 0) cls = 'none';
  else if (down > 0) cls = 'down';
  else if (late > 0) cls = 'late';
  else if (2 * k < e) cls = 'none';
  else cls = 'ok';
  return { cls, e, k, m };
}

export interface Share {
  /** '100%', '99.9%', or null when no check gave a reading. */
  pct: string | null;
  /** The count of days that could hold a reading. */
  days: number;
}

/** The share of the checks that gave a reading and found the part working, over the bars. */
export function shareOf(
  counts: readonly (readonly [number, number, number])[],
  expectedByDay: readonly number[],
): Share {
  let ok = 0;
  let bad = 0;
  let days = 0;
  counts.forEach((triple, i) => {
    ok += triple[0];
    bad += triple[1] + triple[2];
    if ((expectedByDay[i] ?? 0) > 0) days += 1;
  });
  const k = ok + bad;
  if (k === 0) return { pct: null, days };
  if (bad === 0) return { pct: '100%', days };
  return { pct: `${(Math.floor((1000 * ok) / k) / 10).toFixed(1)}%`, days };
}

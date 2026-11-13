/** The types the checker, the store and the page share. No Worker type and no DOM type here. */

/** The four parts of Snowlight the checker looks at, in the order the page names them. */
export type Part = 'site' | 'closings' | 'chances' | 'accounts';
export const PARTS: readonly Part[] = ['site', 'closings', 'chances', 'accounts'];

/** What a check found. `unknown`: the check itself failed, which says nothing about the part. */
export type State = 'ok' | 'late' | 'down' | 'unknown';

/** What one part's check gave at a tick. */
export interface Reading {
  s: State;
  /** HTTP status of the try that stands; 0: no answer. */
  code: number;
  /** Milliseconds to the answer's headers; null: no answer. */
  ms: number | null;
  /** The file's own `generated_at` in Unix seconds, for the two file parts; null: not read. */
  made: number | null;
  /** The seconds of the CDN's `Age` that were allowed, for the two file parts. */
  allow: number;
  /** The body's length, for the closings file; null: no body. */
  bytes: number | null;
}

/** One tick's four readings. `t` is the tick: Unix seconds, a multiple of 300. */
export interface Sample {
  t: number;
  parts: Record<Part, Reading>;
}

/** A day's counts of readings for one part. `day` is 'YYYY-MM-DD', UTC. */
export interface DayRow {
  day: string;
  part: Part;
  ok: number;
  late: number;
  down: number;
}

/** A stretch of readings that were not `ok`. `id` null: not in the store yet. */
export interface Incident {
  id: number | null;
  part: Part;
  /** The worst state in it. */
  kind: 'late' | 'down';
  /** Ticks of its first and latest not-ok sample. */
  start: number;
  last: number;
  /** Null: open. */
  ended: number | null;
  /** 1: the readings stopped while it was going on. */
  gap: 0 | 1;
}

/** An incident as the summary carries it. `l` only while open. */
export interface SummaryIncident {
  p: Part;
  k: 'late' | 'down';
  s: number;
  e: number | null;
  g: 0 | 1;
  l?: number;
}

/** A part in the summary. `made` only for a file part whose stamp was read. */
export interface SummaryPart {
  s: State;
  made?: number;
}

/**
 * The checks of each part that gave no answer (its state was `unknown`, or the tick was not
 * taken at all), as runs: `[the first such tick, how many in a row]`, oldest first. Exact from
 * `since` on; before it the store kept only the counts a UTC day.
 */
export interface Miss {
  since: number;
  runs: Record<Part, [number, number][]>;
}

/** The one document the page draws from, written whole at every tick. */
export interface Summary {
  v: 1;
  /** The tick it was written at. */
  now: number;
  /** The first tick ever taken in. */
  first: number;
  parts: Record<Part, SummaryPart>;
  /** The UTC day of the first of the 90 bars. */
  from: string;
  /** Per part, 90 triples `[ok, late, down]`, oldest first. */
  days: Record<Part, [number, number, number][]>;
  incidents: SummaryIncident[];
  /** Left out by a store written before it was kept: the page then claims no gap it cannot prove. */
  miss?: Miss;
}

/** Seconds in a tick, and ticks in a whole UTC day. */
export const TICK = 300;
export const DAY = 86400;
export const DAYS_KEPT = 90;

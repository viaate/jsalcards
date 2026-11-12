/**
 * Closings announced for later days (the owner's "rings"): the rows of the
 * file shown for a day after their school's own map day (closings.ts
 * Lit.later), as the map's quiet dashed rings (map/later-rings.ts) and the
 * key's "Later days" line (ui/LaterKey.svelte) show them.
 *
 * - Each later day is counted whole: every school of a kind the menu shows
 *   with a row that day, a school lit today too, as the key counts today's,
 *   and, while the map shows two days, a school the day is lit for (the day
 *   lit in the East can be a later day in the West).
 * - A school has one ring at most, for its earliest later day, with that
 *   day's status; none where the map lights it today (its light wins, and its
 *   later days are in its panel), and none where the menu hides its kind or
 *   that status, as it hides a light.
 * - Nor has a school at the place of one the map lights today (under 2 m
 *   apart, as the panel's "Same place"): the glow covers its dot there
 *   (map/glow-mount.ts), and a ring would show through the light, so the
 *   light reads as today's alone. Its later day is in its own panel, which
 *   the lit school's lists as at the same place, and is counted all the same.
 * - A ring near a light the map shows today (LaterMark.near) gives way to the
 *   light's glow until the zoom parts them (map/later-rings.ts), so today's
 *   light never wears a ring at any zoom.
 * - A status code the site does not know (LATER_STATUSES and up) is neither
 *   counted nor ringed, as the key's counts skip it (closings.ts countShown).
 */

import type { LitSchools } from './closings';
import type { LaterRows } from './live';
import { coveredNow } from '../map/same-places-build';
import { showsSchool, showsStatus } from '../state/filter';
import type { MapFilter } from '../state/filter';
import type { LocalDate } from '../types/generated';

/** One later day and how many schools of the kinds shown have a row that day. */
export interface LaterCount {
  readonly day: LocalDate;
  readonly count: number;
}

/** A school's ring: its earliest later day, and that day's status code (0 closed … 3 early). */
export interface LaterMark {
  readonly school: number;
  readonly day: LocalDate;
  readonly status: number;
  /**
   * How far its school is from the nearest light the map shows today, in the
   * map's pixels at zoom 0 (512 to the world's width, as the map's Mercator
   * draws it, so its pixels at zoom z are near * 2^z); Infinity with none within NEAR_REACH.
   */
  readonly near: number;
}

/**
 * How far from a school a light is looked for, in the map's pixels at zoom 0:
 * past it, a light's glow is clear of a ring from the zoom the rings come in
 * at (map/later-rings.ts lightClearZoom, which its tests hold to this).
 */
export const NEAR_REACH = 0.04;

/** The status codes a ring is drawn for: closed, delayed, remote, early dismissal. */
export const LATER_STATUSES = 4;

export interface LaterView {
  /** The later days with a school of a kind shown, earliest first. */
  readonly days: readonly LaterCount[];
  /** One mark a school, in school order. */
  readonly marks: readonly LaterMark[];
  /** The earliest day the map shows (live.ts LaterRows.from), or null with no later day. */
  readonly from: LocalDate | null;
}

export const NO_LATER: LaterView = Object.freeze({ days: [], marks: [], from: null });

/** Whether two views' key lines read the same: the same days, each with the same count. */
export function sameDays(a: LaterView, b: LaterView): boolean {
  return (
    a.from === b.from &&
    a.days.length === b.days.length &&
    a.days.every((entry, i) => {
      const other: LaterCount | undefined = b.days[i];
      return entry.day === other?.day && entry.count === other.count;
    })
  );
}

/** The later days' counts and rings for the file shown, by the menu's filter. */
export function laterView(rows: LaterRows | null, filter: MapFilter): LaterView {
  if (rows === null || rows.days.length === 0) return NO_LATER;
  const { directory, lit } = rows;
  const days: LaterCount[] = [];
  const marked = new Map<number, LaterMark>();
  // Earliest first, so a school's first ring is its earliest later day's.
  const ordered = [...rows.days].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
  for (const { day, schools, statuses, all } of ordered) {
    let count = 0;
    for (let i = 0; i < all.schools.length; i++) {
      const school = all.schools[i] ?? 0;
      if (school >= directory.count || (all.statuses[i] ?? 0) >= LATER_STATUSES) continue;
      if (showsSchool(filter, directory.kind[school] ?? 0)) count++;
    }
    schools.forEach((school, i) => {
      if (school >= directory.count) return;
      const status = statuses[i] ?? 0;
      if (status >= LATER_STATUSES || !showsSchool(filter, directory.kind[school] ?? 0)) return;
      if (lit.schools.has(school) || marked.has(school) || !showsStatus(filter, status)) return;
      marked.set(school, { school, day, status, near: Infinity });
    });
    if (count > 0) days.push({ day, count });
  }
  // The schools at the places of the lights the map shows, which the glow covers: no ring.
  const lights = shownLights(lit, filter);
  if (marked.size > 0 && lights.length > 0) {
    for (const school of coveredNow(directory.e6, lights, [...marked.keys()])) {
      marked.delete(school);
    }
  }
  const near = nearestLights(directory.lngLat, lights, [...marked.keys()]);
  const marks = [...marked.values()]
    .map((mark) => ({ ...mark, near: near.get(mark.school) ?? Infinity }))
    .sort((a, b) => a.school - b.school);
  return days.length === 0 && marks.length === 0 ? NO_LATER : { days, marks, from: rows.from };
}

/** The schools the glow lights by the menu's filter, as data/closings.ts filterLit keeps them. */
function shownLights(lit: LitSchools, filter: MapFilter): Int32Array {
  const shown: number[] = [];
  let row = 0;
  // The lit schools are in row order (closings.ts LitSchools.schools).
  for (const school of lit.schools) {
    if (showsStatus(filter, lit.status[row] ?? 0) && showsSchool(filter, lit.kinds[row] ?? 0)) {
      shown.push(school);
    }
    row++;
  }
  return Int32Array.from(shown);
}

/** A place's x and y on the map at zoom 0, in its pixels (512 to the world's width). */
function worldXY(lngLat: Float64Array, school: number): readonly [number, number] {
  const lon = lngLat[school * 2] ?? 0;
  const lat = Math.max(-85.05, Math.min(85.05, lngLat[school * 2 + 1] ?? 0));
  const y = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  return [((lon + 180) / 360) * 512, (0.5 - y / (2 * Math.PI)) * 512];
}

/**
 * Each of `schools`' distance to the nearest of `lights`, in the map's pixels
 * at zoom 0, for those with one within NEAR_REACH: the lights are put in
 * squares NEAR_REACH wide, and each school looks in its own square and the
 * eight around it.
 */
export function nearestLights(
  lngLat: Float64Array,
  lights: Iterable<number>,
  schools: readonly number[],
): Map<number, number> {
  const near = new Map<number, number>();
  if (schools.length === 0) return near;
  const cells = new Map<string, [number, number][]>();
  for (const light of lights) {
    const [x, y] = worldXY(lngLat, light);
    const key = `${String(Math.floor(x / NEAR_REACH))},${String(Math.floor(y / NEAR_REACH))}`;
    const cell = cells.get(key);
    if (cell === undefined) cells.set(key, [[x, y]]);
    else cell.push([x, y]);
  }
  for (const school of schools) {
    const [x, y] = worldXY(lngLat, school);
    const cx = Math.floor(x / NEAR_REACH);
    const cy = Math.floor(y / NEAR_REACH);
    let best = Infinity;
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const [lx, ly] of cells.get(`${String(cx + dx)},${String(cy + dy)}`) ?? []) {
          best = Math.min(best, Math.hypot(lx - x, ly - y));
        }
      }
    }
    if (best <= NEAR_REACH) near.set(school, best);
  }
  return near;
}

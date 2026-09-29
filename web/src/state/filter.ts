/**
 * What the map shows, as the menu sets it (ui/MenuPanel.svelte): today's
 * lights in all four statuses or in one of them, and the schools of each
 * kind, public and private. It lasts while the page is open; every visit
 * starts with everything shown, so no one comes back to a map that hides
 * schools without their knowing.
 *
 * The glow shows only the lit schools it picks (data/closings.ts
 * filterLit), and the school dots and names only the kinds it keeps
 * (map/basemap/schools.ts schoolKindFilter).
 */

import type { Status } from '../types/generated';

export interface MapFilter {
  /** The one status whose lights show, by code; null for all four. */
  readonly status: Status | null;
  /** Whether public schools show (charter schools among them). */
  readonly public: boolean;
  /** Whether private schools show. */
  readonly private: boolean;
}

/** A school's kind, as the menu names it. */
export type SchoolKind = 'public' | 'private';

export const SCHOOL_KINDS: readonly SchoolKind[] = Object.freeze(['public', 'private']);

/** Everything: the map as it opens. */
export const SHOW_ALL: MapFilter = Object.freeze({ status: null, public: true, private: true });

/** The kind flag points.bin and the school tiles set on a private school (pipeline/snowlight/directory/points.py). */
export const PRIVATE_FLAG = 0x01;

/** Whether the map shows schools of both kinds. */
export function showsBothKinds(filter: MapFilter): boolean {
  return filter.public && filter.private;
}

/** Whether the map shows everything, as it opens. */
export function showsAll(filter: MapFilter): boolean {
  return filter.status === null && showsBothKinds(filter);
}

/** Whether a school with these kind flags shows. */
export function showsSchool(filter: MapFilter, flags: number): boolean {
  return (flags & PRIVATE_FLAG) === 0 ? filter.public : filter.private;
}

/** Whether a light in this status shows. */
export function showsStatus(filter: MapFilter, status: number): boolean {
  return filter.status === null || filter.status === status;
}

/** The same filter with one kind shown or not. */
export function withKind(filter: MapFilter, kind: SchoolKind, shown: boolean): MapFilter {
  return Object.freeze({ ...filter, [kind]: shown });
}

/** The same filter showing the lights of one status, or of all four with null. */
export function withStatus(filter: MapFilter, status: Status | null): MapFilter {
  return Object.freeze({ ...filter, status });
}

/** Whether two filters show the same. */
export function sameFilter(a: MapFilter, b: MapFilter): boolean {
  return a.status === b.status && a.public === b.public && a.private === b.private;
}

/**
 * schools/areas/: the schools around each ZIP code, for the area panel a ZIP
 * code opens, staged from the directory's own tables and the places build's
 * ZIP codes (scripts/stage-data.mjs). Opening a ZIP code reads two small
 * files, never the whole directory:
 *
 *   schools/areas/index.json   where each shard starts, and its file's name
 *     {"schema_version": 1, "directory": <stamp>, "shards": <count>,
 *      "first_zips": [<zip>, ...], "files": ["0.<hash>.json", ...]}
 *   schools/areas/<n>.json     ZIPS_PER_SHARD ZIP codes, in order of their codes
 *     {"schema_version": 1, "directory": <stamp>, "first": <zip>, "areas": [<area>, ...]}
 *
 * As with the school details (details-format.ts), the build's list of data
 * files lists the index alone, which names each shard's file with its content
 * hash (`isAreaShard`). <stamp> is the directory the positions point into.
 *
 * An area is AREA_COLUMNS in order:
 *
 *   zip     the ZIP code (a Census ZCTA, as search finds it)
 *   lon, lat  its point, as the places build gives it
 *   states  the USPS codes of the states it is in, most land first
 *   own     the schools whose ZIP code in the directory is this one, nearest
 *           its point first: each [position, id, metres, longitude, latitude],
 *           its place as points.bin gives it and metres from the ZIP's point.
 *           Virtual schools are left out (weather does not close them), and so
 *           is a school farther than AREA_OWN_METRES from the point: its ZIP
 *           code is another place's (a charter school listed at its main
 *           office's, or one written wrong).
 *   near    with fewer than AREA_MIN_SCHOOLS of its own, the nearest other
 *           schools within AREA_NEAR_METRES of its point, up to that many in
 *           all, nearest first, in the same form; otherwise none. Virtual
 *           schools are left out here too.
 *
 * Ties in distance go to the school first in the directory.
 *
 * This module has no imports, so Node can load it directly from the scripts.
 */

/** ZIP codes per shard: about 15 KB compressed each. */
export const ZIPS_PER_SHARD = 128;

/** The shard index, as the page asks for it (its plain name). */
export const AREAS_INDEX_PATH = 'schools/areas/index.json';

const METRES_PER_MILE = 1609.344;

/** Fewer schools of its own than this, and a ZIP code's area takes in the nearest others. */
export const AREA_MIN_SCHOOLS = 6;
/** How far from a ZIP code's point, in miles, the nearest others are taken in. */
export const AREA_NEAR_MILES = 2;
export const AREA_NEAR_METRES = AREA_NEAR_MILES * METRES_PER_MILE;
/** A school farther than this from its ZIP code's point is in another place: 25 miles. */
export const AREA_OWN_METRES = 25 * METRES_PER_MILE;

/** Shard `n`'s plain name, as staging writes it before it hashes it. */
export function areasShardPath(n: number): string {
  return `schools/areas/${String(n)}.json`;
}

/** A shard's file name as the index names it: "12.0123456789.json", or "12.json" unhashed. */
export const AREA_SHARD_FILE = /^\d+(?:\.[0-9a-f]{10})?\.json$/;

/** Whether a data file is an area shard, which the page reaches through the index, not the build's list. */
export function isAreaShard(path: string): boolean {
  return (
    path.startsWith('schools/areas/') && AREA_SHARD_FILE.test(path.slice('schools/areas/'.length))
  );
}

/** Columns of an area, in order. */
export const AREA_COLUMNS = ['zip', 'lon', 'lat', 'states', 'own', 'near'] as const;

/** A school in an area: [position, id, metres from the ZIP's point, longitude, latitude]. */
export type AreaEntry = readonly [
  position: number,
  id: string,
  metres: number,
  lon: number,
  lat: number,
];

/** One area as written: AREA_COLUMNS in order. */
export type AreaRow = readonly [
  zip: string,
  lon: number,
  lat: number,
  states: readonly string[],
  own: readonly AreaEntry[],
  near: readonly AreaEntry[],
];

const ZIP = /^\d{5}$/;
const STATE = /^[A-Z]{2}$/;
const SCHOOL_ID = /^(?:\d{12}|[0-9A-Z]{8})$/;
const MAX_COUNT = 4_294_967_294;
/** Schools one ZIP code has at most, with room: the busiest has about a hundred. */
const MAX_OWN = 1000;

function isLon(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 180;
}

function isLat(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 90;
}

function isEntry(value: unknown, maxMetres: number): boolean {
  if (!Array.isArray(value) || value.length !== 5) return false;
  const [position, id, metres, lon, lat] = value as unknown[];
  return (
    typeof position === 'number' &&
    Number.isSafeInteger(position) &&
    position >= 0 &&
    position <= MAX_COUNT &&
    typeof id === 'string' &&
    SCHOOL_ID.test(id) &&
    typeof metres === 'number' &&
    Number.isSafeInteger(metres) &&
    metres >= 0 &&
    metres <= Math.floor(maxMetres) &&
    isLon(lon) &&
    isLat(lat)
  );
}

/** Whether a list of entries is nearest first, ties by position, each school once. */
function inOrder(entries: readonly AreaEntry[]): boolean {
  return entries.every((entry, i) => {
    const before = entries[i - 1];
    return (
      before === undefined ||
      before[2] < entry[2] ||
      (before[2] === entry[2] && before[0] < entry[0])
    );
  });
}

/** Whether a value is an area as the format writes it. */
export function isAreaRow(value: unknown): value is AreaRow {
  if (!Array.isArray(value) || value.length !== AREA_COLUMNS.length) return false;
  const [zip, lon, lat, states, own, near] = value as unknown[];
  if (typeof zip !== 'string' || !ZIP.test(zip) || !isLon(lon) || !isLat(lat)) return false;
  if (!Array.isArray(states) || states.length === 0) return false;
  if (!states.every((state) => typeof state === 'string' && STATE.test(state))) return false;
  if (!Array.isArray(own) || !Array.isArray(near) || own.length > MAX_OWN) return false;
  if (!own.every((entry) => isEntry(entry, AREA_OWN_METRES))) return false;
  if (!near.every((entry) => isEntry(entry, AREA_NEAR_METRES))) return false;
  // Others are taken in only to make up AREA_MIN_SCHOOLS, and never one of its own twice.
  if (near.length > 0 && own.length + near.length > AREA_MIN_SCHOOLS) return false;
  const typedOwn = own as AreaEntry[];
  const typedNear = near as AreaEntry[];
  if (!inOrder(typedOwn) || !inOrder(typedNear)) return false;
  const positions = new Set([...typedOwn, ...typedNear].map((entry) => entry[0]));
  return positions.size === own.length + near.length;
}

/** The shard a ZIP code would be in, from the shards' first ZIP codes; -1 before the first. */
export function zipShardOf(firstZips: readonly string[], zip: string): number {
  let low = 0;
  let high = firstZips.length;
  // The last shard whose first ZIP code is at or before `zip`.
  while (low < high) {
    const middle = (low + high) >>> 1;
    if ((firstZips[middle] ?? '') <= zip) low = middle + 1;
    else high = middle;
  }
  return low - 1;
}

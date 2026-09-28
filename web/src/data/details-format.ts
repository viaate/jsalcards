/**
 * schools/details/: what the directory says about each school, for its
 * detail panel, staged from the directory build's own tables
 * (scripts/stage-data.mjs). Opening one school reads two small files and
 * never the whole directory:
 *
 *   schools/details/index.json   where each shard starts, and its file's name
 *     {"schema_version": 1, "directory": <stamp>, "shards": <count>,
 *      "first_ids": [<id>, ...], "files": ["0.<hash>.json", ...]}
 *   schools/details/<n>.json     SCHOOLS_PER_SHARD schools in meta.json order
 *     {"schema_version": 1, "directory": <stamp>, "first": <position>, "rows": [<row>, ...]}
 *
 * The page finds a shard through the index, which names each shard's file in
 * the same folder (with its content hash, as staged): the build's list of
 * data files (tools/data-files.ts) lists the index alone, not the hundreds of
 * shards (`isDetailShard`).
 *
 * <stamp> is the directory the files point into, {"generated_on", "schools",
 * "districts"}, as live files carry it. A row is DETAIL_COLUMNS in order:
 *
 *   id            the school's NCES id
 *   name          its name as the directory spells it
 *   flags         points.bin's kind flags: 0x01 private, 0x02 charter, 0x04 virtual
 *   district      its district's position in meta.json districts, or null
 *   districtId    that district's NCES id, or null
 *   districtName  that district's name as the directory spells it, or null
 *   street, city  as NCES writes them (often in capitals), or null
 *   state         the USPS code
 *   zip           5 digits, or null
 *   county        the county's name, or null
 *   gradeLow, gradeHigh   NCES grade codes (GRADE_CODES), or null
 *   enrollment    students, or null where NCES reports none
 *   phone         10 digits, or null
 *   nearby        the nearest other schools within NEARBY_MAX_METRES, nearest
 *                 first, at most NEARBY_COUNT: each [position, id, name, metres,
 *                 longitude, latitude], its name as the directory spells it and
 *                 its place in degrees (points.bin); virtual schools are not listed
 *
 * Schools are in meta.json order, public schools (12-digit ids) sorted by id,
 * then private schools (8-character ids) sorted by id, so a school's shard is
 * found from the first ids alone (`shardOf`).
 *
 * This module has no imports, so Node can load it directly from the scripts.
 */

/** Schools per shard: about 25 KB compressed each. */
export const SCHOOLS_PER_SHARD = 256;

/** The shard index, as the page asks for it (its plain name). */
export const DETAILS_INDEX_PATH = 'schools/details/index.json';

/** Shard `n`'s plain name, as staging writes it before it hashes it. */
export function detailsShardPath(n: number): string {
  return `schools/details/${String(n)}.json`;
}

/** A shard's file name as the index names it: "12.0123456789.json", or "12.json" unhashed. */
export const SHARD_FILE = /^\d+(?:\.[0-9a-f]{10})?\.json$/;

/** Whether a data file is a shard, which the page reaches through the index, not the build's list. */
export function isDetailShard(path: string): boolean {
  return (
    path.startsWith('schools/details/') && SHARD_FILE.test(path.slice('schools/details/'.length))
  );
}

/** Columns of a row, in order. */
export const DETAIL_COLUMNS = [
  'id',
  'name',
  'flags',
  'district',
  'districtId',
  'districtName',
  'street',
  'city',
  'state',
  'zip',
  'county',
  'gradeLow',
  'gradeHigh',
  'enrollment',
  'phone',
  'nearby',
] as const;

/** Schools a row lists as nearby, at most. */
export const NEARBY_COUNT = 4;
/** How far a school may be and still be listed as nearby: 5 miles. */
export const NEARBY_MAX_METRES = 8047;

/** A school near another: [position, id, name, metres, longitude, latitude]. */
export type NearbyEntry = readonly [
  position: number,
  id: string,
  name: string,
  metres: number,
  lon: number,
  lat: number,
];

/** One row as written: DETAIL_COLUMNS in order. */
export type DetailRow = readonly [
  id: string,
  name: string,
  flags: number,
  district: number | null,
  districtId: string | null,
  districtName: string | null,
  street: string | null,
  city: string | null,
  state: string,
  zip: string | null,
  county: string | null,
  gradeLow: string | null,
  gradeHigh: string | null,
  enrollment: number | null,
  phone: string | null,
  nearby: readonly NearbyEntry[],
];

/** Kind flags (points.bin). */
export const KIND_FLAGS = Object.freeze({ private: 0x01, charter: 0x02, virtual: 0x04 });

/** NCES grade codes, lowest first. */
export const GRADE_CODES: readonly string[] = Object.freeze([
  'PK',
  'TK',
  'KG',
  '01',
  '02',
  '03',
  '04',
  '05',
  '06',
  '07',
  '08',
  '09',
  '10',
  '11',
  '12',
  '13',
]);

const TEXT_MAX = 200;
const SCHOOL_ID = /^(?:\d{12}|[0-9A-Z]{8})$/;
const DISTRICT_ID = /^\d{7}$/;
const STATE = /^[A-Z]{2}$/;
const ZIP = /^\d{5}$/;
const PHONE = /^[2-9]\d{9}$/;
const MAX_COUNT = 4_294_967_294;
const MAX_ENROLLMENT = 1_000_000;

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.trim() !== '' && value.length <= TEXT_MAX;
}

function textOrNull(value: unknown): boolean {
  return value === null || isText(value);
}

function matchOrNull(value: unknown, pattern: RegExp): boolean {
  return value === null || (typeof value === 'string' && pattern.test(value));
}

function wholeOrNull(value: unknown, max: number): boolean {
  return (
    value === null ||
    (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max)
  );
}

function gradeOrNull(value: unknown): boolean {
  return value === null || (typeof value === 'string' && GRADE_CODES.includes(value));
}

function isNearbyEntry(value: unknown): boolean {
  if (!Array.isArray(value) || value.length !== 6) return false;
  const [position, id, name, metres, lon, lat] = value as unknown[];
  return (
    wholeOrNull(position, MAX_COUNT) &&
    position !== null &&
    typeof id === 'string' &&
    SCHOOL_ID.test(id) &&
    isText(name) &&
    typeof metres === 'number' &&
    Number.isInteger(metres) &&
    metres >= 0 &&
    metres <= NEARBY_MAX_METRES &&
    typeof lon === 'number' &&
    Math.abs(lon) <= 180 &&
    typeof lat === 'number' &&
    Math.abs(lat) <= 90
  );
}

/** Whether a value is a row as the format writes it. */
export function isDetailRow(value: unknown): value is DetailRow {
  if (!Array.isArray(value) || value.length !== DETAIL_COLUMNS.length) return false;
  const [id, name, flags, district, districtId, districtName, ...rest] = value as unknown[];
  const [street, city, state, zip, county, low, high, enrollment, phone, nearby] = rest;
  const inDistrict = district !== null;
  return (
    typeof id === 'string' &&
    SCHOOL_ID.test(id) &&
    isText(name) &&
    typeof flags === 'number' &&
    Number.isInteger(flags) &&
    flags >= 0 &&
    flags <= 0x07 &&
    wholeOrNull(district, MAX_COUNT) &&
    // A district's id and name come with its position, or none of them do.
    (inDistrict
      ? typeof districtId === 'string' && DISTRICT_ID.test(districtId) && isText(districtName)
      : districtId === null && districtName === null) &&
    textOrNull(street) &&
    textOrNull(city) &&
    typeof state === 'string' &&
    STATE.test(state) &&
    matchOrNull(zip, ZIP) &&
    textOrNull(county) &&
    gradeOrNull(low) &&
    gradeOrNull(high) &&
    wholeOrNull(enrollment, MAX_ENROLLMENT) &&
    matchOrNull(phone, PHONE) &&
    Array.isArray(nearby) &&
    nearby.length <= NEARBY_COUNT &&
    nearby.every(isNearbyEntry)
  );
}

/**
 * The order of the directory's ids: public schools (12 digits) first, then
 * private schools (8 characters), each sorted by id. Negative when `a` comes
 * before `b`.
 */
export function compareSchoolIds(a: string, b: string): number {
  const privateA = a.length === 8 ? 1 : 0;
  const privateB = b.length === 8 ? 1 : 0;
  if (privateA !== privateB) return privateA - privateB;
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The shard a school id would be in, from the shards' first ids; -1 before the first. */
export function shardOf(firstIds: readonly string[], id: string): number {
  let low = 0;
  let high = firstIds.length;
  // The last shard whose first id is at or before `id`.
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (compareSchoolIds(firstIds[middle] ?? '', id) <= 0) low = middle + 1;
    else high = middle;
  }
  return low - 1;
}

const EARTH_RADIUS_METRES = 6_371_008.8;

/** The distance between two places on the Earth, in metres (haversine, on the mean radius). */
export function metresBetween(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_METRES * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** A phone number as NCES writes it ("(573)859-3326", "8169361230"): its 10 digits, or null. */
export function phoneDigits(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const digits = raw.replace(/\D/gu, '');
  const ten = digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits;
  return PHONE.test(ten) ? ten : null;
}

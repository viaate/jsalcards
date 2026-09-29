/**
 * The school directory: schools/meta.json (ids and names) and
 * schools/points.bin (where each school is), read together.
 *
 * Every other published file points into the directory by position, and
 * carries a stamp saying which directory it was written against. A file
 * whose stamp does not match the loaded directory is not read with it.
 *
 * points.bin (pipeline/snowlight/directory/points.py), little-endian:
 *
 *   header, 16 bytes: "SLPT", u16 format version, u16 record size (13),
 *                     u32 school count, u32 district count
 *   one 13-byte record per school, in meta.json order:
 *                     i32 longitude and i32 latitude in millionths of a degree,
 *                     u32 district index (0xFFFFFFFF for none), u8 kind flags
 */

import { PUBLISHED_PATHS } from '../types/generated';
import type { DirectoryStamp, DistrictId, SchoolDirectoryMeta, SchoolId } from '../types/generated';
import { DATA_PATHS, fetchBytes, fetchJson } from './files';
import type { DataFiles, Fetch } from './files';

const MAGIC = 'SLPT';
const FORMAT_VERSION = 1;
const HEADER_BYTES = 16;
const RECORD_BYTES = 13;
const NO_DISTRICT = 0xffffffff;
const MICRODEGREES = 1e-6;
const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SCHOOL_YEAR = /^\d{4}-\d{4}$/;

/** Where the directory puts each school. */
export interface Points {
  /** Longitude, latitude of each school in degrees, interleaved, in meta.json order. */
  readonly lngLat: Float64Array;
  /** Each school's position in meta.json districts, or -1 for none. */
  readonly district: Int32Array;
  /** Each school's kind flags: 0x01 private, 0x02 charter, 0x04 exclusively virtual. */
  readonly kind: Uint8Array;
}

export interface Directory extends Points {
  readonly meta: SchoolDirectoryMeta;
  readonly count: number;
  /** A school's position, or -1 when the directory has no such school. */
  schoolIndex(id: SchoolId): number;
  /** A district's position in meta.json districts, or -1. */
  districtIndex(id: DistrictId): number;
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isStringArray(value: unknown, length: number): value is readonly string[] {
  return (
    Array.isArray(value) &&
    value.length === length &&
    value.every((item) => typeof item === 'string')
  );
}

/** meta.json, checked where the page depends on it; null for anything else. */
export function parseMeta(value: unknown): SchoolDirectoryMeta | null {
  if (typeof value !== 'object' || value === null) return null;
  const meta = value as Record<string, unknown>;
  const { districts, school_years: years } = meta;
  if (meta.schema_version !== 1) return null;
  if (typeof meta.generated_on !== 'string' || !LOCAL_DATE.test(meta.generated_on)) return null;
  if (!isCount(meta.count)) return null;
  if (!isStringArray(meta.ids, meta.count) || !isStringArray(meta.names, meta.count)) return null;
  if (typeof districts !== 'object' || districts === null) return null;
  const { ids, names } = districts as Record<string, unknown>;
  if (!Array.isArray(ids) || !isStringArray(ids, ids.length) || !isStringArray(names, ids.length)) {
    return null;
  }
  if (typeof years !== 'object' || years === null) return null;
  const { public: publicYear, private: privateYear } = years as Record<string, unknown>;
  if (typeof publicYear !== 'string' || !SCHOOL_YEAR.test(publicYear)) return null;
  if (typeof privateYear !== 'string' || !SCHOOL_YEAR.test(privateYear)) return null;
  return value as SchoolDirectoryMeta;
}

/** points.bin's header, when `bytes` is a whole points file: its view and counts. */
function pointsHeader(
  bytes: ArrayBuffer,
): { view: DataView; count: number; districts: number } | null {
  if (bytes.byteLength < HEADER_BYTES) return null;
  const view = new DataView(bytes);
  const magic = String.fromCharCode(
    view.getUint8(0),
    view.getUint8(1),
    view.getUint8(2),
    view.getUint8(3),
  );
  if (magic !== MAGIC || view.getUint16(4, true) !== FORMAT_VERSION) return null;
  if (view.getUint16(6, true) !== RECORD_BYTES) return null;
  const count = view.getUint32(8, true);
  if (bytes.byteLength !== HEADER_BYTES + RECORD_BYTES * count) return null;
  return { view, count, districts: view.getUint32(12, true) };
}

/** points.bin for `meta`; null when it is not one, or not the same directory's. */
export function parsePoints(bytes: ArrayBuffer, meta: SchoolDirectoryMeta): Points | null {
  const header = pointsHeader(bytes);
  if (header === null) return null;
  const { view, count, districts } = header;
  if (count !== meta.count || districts !== meta.districts.ids.length) return null;

  const lngLat = new Float64Array(count * 2);
  const district = new Int32Array(count);
  const kind = new Uint8Array(count);
  for (let i = 0, at = HEADER_BYTES; i < count; i++, at += RECORD_BYTES) {
    const lon = view.getInt32(at, true) * MICRODEGREES;
    const lat = view.getInt32(at + 4, true) * MICRODEGREES;
    const index = view.getUint32(at + 8, true);
    if (Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;
    if (index !== NO_DISTRICT && index >= districts) return null;
    lngLat[i * 2] = lon;
    lngLat[i * 2 + 1] = lat;
    district[i] = index === NO_DISTRICT ? -1 : index;
    kind[i] = view.getUint8(at + 12);
  }
  return { lngLat, district, kind };
}

/** Where every school is and its kind flags, in directory order: all the map's dust needs. */
export type Positions = Pick<Points, 'lngLat' | 'kind'>;

/**
 * Where every school is and what kind it is, from points.bin alone, for a
 * reader that needs no names (the map's dust). Null when it is not a points
 * file.
 */
export function parsePositions(bytes: ArrayBuffer): Positions | null {
  const header = pointsHeader(bytes);
  if (header === null) return null;
  const { view, count } = header;
  const lngLat = new Float64Array(count * 2);
  const kind = new Uint8Array(count);
  for (let i = 0, at = HEADER_BYTES; i < count; i++, at += RECORD_BYTES) {
    const lon = view.getInt32(at, true) * MICRODEGREES;
    const lat = view.getInt32(at + 4, true) * MICRODEGREES;
    if (Math.abs(lon) > 180 || Math.abs(lat) > 90) return null;
    lngLat[i * 2] = lon;
    lngLat[i * 2 + 1] = lat;
    kind[i] = view.getUint8(at + 12);
  }
  return { lngLat, kind };
}

/** Positions by id, built on first use: a lookup table for 100,000 ids takes a moment. */
function lookup(ids: readonly string[]): (id: string) => number {
  let table: Map<string, number> | null = null;
  return (id) => {
    table ??= new Map(ids.map((value, index) => [value, index]));
    return table.get(id) ?? -1;
  };
}

export function createDirectory(meta: SchoolDirectoryMeta, points: Points): Directory {
  return {
    meta,
    count: meta.count,
    lngLat: points.lngLat,
    district: points.district,
    kind: points.kind,
    schoolIndex: lookup(meta.ids),
    districtIndex: lookup(meta.districts.ids),
  };
}

/**
 * Loads the directory this build ships. Null, quietly, when it does not ship
 * one or the two files cannot be read together.
 */
export async function loadDirectory(
  files: DataFiles,
  init: RequestInit = {},
  fetchImpl?: Fetch,
  /** points.bin, when it is already on its way. */
  pointBytes?: Promise<ArrayBuffer | null>,
): Promise<Directory | null> {
  if (!files.has(PUBLISHED_PATHS.schoolDirectory) || !files.has(DATA_PATHS.points)) return null;
  const [rawMeta, bytes] = await Promise.all([
    fetchJson(files, PUBLISHED_PATHS.schoolDirectory, init, fetchImpl),
    pointBytes ?? fetchBytes(files, DATA_PATHS.points, init, fetchImpl),
  ]);
  const meta = parseMeta(rawMeta);
  if (meta === null || bytes === null) return null;
  const points = parsePoints(bytes, meta);
  return points === null ? null : createDirectory(meta, points);
}

/** Whether a file stamped with `stamp` points into `directory`. */
export function sameDirectory(directory: Directory, stamp: DirectoryStamp): boolean {
  return (
    stamp.generated_on === directory.meta.generated_on &&
    stamp.schools === directory.count &&
    stamp.districts === directory.meta.districts.ids.length
  );
}

export interface LngLat {
  readonly lon: number;
  readonly lat: number;
}

/** Where a school is, or null when the directory has no such school. */
export function schoolLocation(directory: Directory, id: SchoolId): LngLat | null {
  const index = directory.schoolIndex(id);
  if (index < 0) return null;
  return { lon: directory.lngLat[index * 2] ?? 0, lat: directory.lngLat[index * 2 + 1] ?? 0 };
}

/** [west, south, east, north] around a district's schools, or null when it has none. */
export function districtBounds(
  directory: Directory,
  id: DistrictId,
): [number, number, number, number] | null {
  const target = directory.districtIndex(id);
  if (target < 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (let i = 0; i < directory.count; i++) {
    if (directory.district[i] !== target) continue;
    const lon = directory.lngLat[i * 2] ?? 0;
    const lat = directory.lngLat[i * 2 + 1] ?? 0;
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return west === Infinity ? null : [west, south, east, north];
}

export interface DirectorySource {
  /**
   * The directory, loaded once. With a stamp, the directory that stamp names:
   * when the loaded one is older (a cached copy from before a deploy), the
   * cached files are dropped and loaded again, once. Null when there is none.
   */
  get(stamp?: DirectoryStamp): Promise<Directory | null>;
  /**
   * Where every school is, from points.bin alone (parsePositions): the same
   * download the directory reads, so reading both fetches it once. Null when
   * the build ships no directory or the file cannot be read.
   */
  positions(): Promise<Positions | null>;
}

export interface DirectorySourceOptions {
  readonly fetch?: Fetch;
  /** Drops cached copies of these URLs, so the next fetch reaches the server. */
  readonly evict?: (urls: readonly string[]) => Promise<void>;
}

export function directorySource(
  files: DataFiles,
  options: DirectorySourceOptions = {},
): DirectorySource {
  let loading: Promise<Directory | null> | null = null;
  let points: Promise<ArrayBuffer | null> | null = null;
  let reloaded = false;
  const shipped = files.has(PUBLISHED_PATHS.schoolDirectory) && files.has(DATA_PATHS.points);
  const pointBytes = (): Promise<ArrayBuffer | null> =>
    (points ??= fetchBytes(files, DATA_PATHS.points, {}, options.fetch).catch(() => null));
  const load = (): Promise<Directory | null> =>
    shipped
      ? loadDirectory(files, {}, options.fetch, pointBytes()).catch(() => null)
      : Promise.resolve(null);
  return {
    async get(stamp) {
      loading ??= load();
      const directory = await loading;
      if (directory === null || stamp === undefined || sameDirectory(directory, stamp)) {
        return directory;
      }
      if (reloaded || options.evict === undefined) return null;
      reloaded = true;
      const urls = [PUBLISHED_PATHS.schoolDirectory, DATA_PATHS.points]
        .map((path) => files.url(path))
        .filter((url): url is string => url !== null);
      loading = options
        .evict(urls)
        .catch(() => undefined)
        .then(() => {
          points = null;
          return load();
        });
      const fresh = await loading;
      return fresh !== null && sameDirectory(fresh, stamp) ? fresh : null;
    },
    async positions() {
      if (!shipped) return null;
      const bytes = await pointBytes();
      return bytes === null ? null : parsePositions(bytes);
    },
  };
}

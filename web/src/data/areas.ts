/**
 * Reads the schools around a ZIP code (areas-format.ts): the shard index
 * once, then the one shard the ZIP code is in. Each file is read once per
 * page; a file that cannot be read, or does not match its format, reads as
 * nothing, and is asked for again the next time.
 */

import type { DirectoryStamp } from '../types/generated';
import { AREAS_INDEX_PATH, AREA_SHARD_FILE, isAreaRow, zipShardOf } from './areas-format';
import type { AreaEntry, AreaRow } from './areas-format';
import { fetchFile, fetchJson } from './files';
import type { DataFiles, Fetch } from './files';

/** A school around a ZIP code. */
export interface AreaSchoolEntry {
  /** Its position in the directory. */
  readonly index: number;
  readonly id: string;
  /** From the ZIP code's point. */
  readonly metres: number;
  readonly lon: number;
  readonly lat: number;
}

/** A ZIP code and the schools around it, as the area files give them. */
export interface AreaRecord {
  readonly zip: string;
  readonly lon: number;
  readonly lat: number;
  /** USPS codes, most land first. */
  readonly states: readonly string[];
  /** Its own schools, nearest its point first. */
  readonly own: readonly AreaSchoolEntry[];
  /** With fewer than AREA_MIN_SCHOOLS of its own, the nearest others within AREA_NEAR_METRES. */
  readonly near: readonly AreaSchoolEntry[];
  /** The directory the positions point into. */
  readonly directory: DirectoryStamp;
}

interface Shard {
  readonly first: string;
  readonly areas: readonly AreaRow[];
  readonly directory: DirectoryStamp;
}

interface ShardIndex {
  readonly firstZips: readonly string[];
  readonly files: readonly string[];
  readonly directory: DirectoryStamp;
}

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ZIP = /^\d{5}$/;
const MAX_COUNT = 4_294_967_294;

function isCount(value: unknown): value is number {
  return (
    typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= MAX_COUNT
  );
}

function parseStamp(value: unknown): DirectoryStamp | null {
  if (typeof value !== 'object' || value === null) return null;
  const { generated_on: day, schools, districts } = value as Record<string, unknown>;
  if (typeof day !== 'string' || !LOCAL_DATE.test(day)) return null;
  if (!isCount(schools) || !isCount(districts)) return null;
  return { generated_on: day, schools, districts };
}

function sameStamp(a: DirectoryStamp, b: DirectoryStamp): boolean {
  return (
    a.generated_on === b.generated_on && a.schools === b.schools && a.districts === b.districts
  );
}

/** index.json, checked; null for anything else. */
export function parseAreaIndex(value: unknown): ShardIndex | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  const directory = parseStamp(file.directory);
  const zips = file.first_zips;
  const names = file.files;
  if (file.schema_version !== 1 || directory === null) return null;
  if (!Array.isArray(zips) || !Array.isArray(names)) return null;
  if (file.shards !== zips.length || zips.length === 0 || names.length !== zips.length) return null;
  if (
    !zips.every(
      (zip, i) => typeof zip === 'string' && ZIP.test(zip) && (i === 0 || zips[i - 1] < zip),
    )
  ) {
    return null;
  }
  if (!names.every((name) => typeof name === 'string' && AREA_SHARD_FILE.test(name))) return null;
  return { firstZips: zips as string[], files: names as string[], directory };
}

/** A shard, checked area by area; null for anything else. */
export function parseAreaShard(value: unknown): Shard | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  const directory = parseStamp(file.directory);
  const { first, areas } = file;
  if (file.schema_version !== 1 || directory === null) return null;
  if (typeof first !== 'string' || !Array.isArray(areas) || areas.length === 0) return null;
  if (!areas.every(isAreaRow)) return null;
  const rows = areas;
  if (rows[0]?.[0] !== first) return null;
  // In order of their codes, each once, every position inside the directory.
  for (const [i, row] of rows.entries()) {
    const before = rows[i - 1];
    if (before !== undefined && before[0] >= row[0]) return null;
    if (![...row[4], ...row[5]].every(([position]) => position < directory.schools)) return null;
  }
  return { first, areas: rows, directory };
}

function entryOf([index, id, metres, lon, lat]: AreaEntry): AreaSchoolEntry {
  return { index, id, metres, lon, lat };
}

/** An area as a record, pointing into `directory`. */
export function areaOf(row: AreaRow, directory: DirectoryStamp): AreaRecord {
  const [zip, lon, lat, states, own, near] = row;
  return {
    zip,
    lon,
    lat,
    states,
    own: own.map(entryOf),
    near: near.map(entryOf),
    directory,
  };
}

export interface AreaSource {
  /** Whether this build ships the area files at all. */
  readonly shipped: boolean;
  /** The ZIP code's area, or null when this build ships none or the ZIP code is not in it. */
  get(zip: string): Promise<AreaRecord | null>;
}

export function createAreaSource(files: DataFiles, fetchImpl: Fetch = fetchFile): AreaSource {
  let index: Promise<ShardIndex | null> | null = null;
  const shards = new Map<number, Promise<Shard | null>>();
  const readIndex = async (): Promise<ShardIndex | null> => {
    try {
      return parseAreaIndex(await fetchJson(files, AREAS_INDEX_PATH, {}, fetchImpl));
    } catch {
      return null;
    }
  };
  /** A shard, by its name in the index's folder. */
  const readShard = async (name: string): Promise<Shard | null> => {
    const base = files.url(AREAS_INDEX_PATH);
    if (base === null) return null;
    try {
      const response = await fetchImpl(new URL(name, base).href);
      return response.ok ? parseAreaShard((await response.json()) as unknown) : null;
    } catch {
      return null;
    }
  };
  const shipped = files.has(AREAS_INDEX_PATH);
  return {
    shipped,
    async get(zip) {
      if (!shipped || !ZIP.test(zip)) return null;
      const reading = (index ??= readIndex());
      const found = await reading;
      // A file that cannot be read is asked for again next time: the failure can pass.
      if (found === null) {
        if (index === reading) index = null;
        return null;
      }
      const n = zipShardOf(found.firstZips, zip);
      const name = found.files[n];
      if (name === undefined) return null;
      let shard = shards.get(n);
      if (shard === undefined) {
        shard = readShard(name);
        shards.set(n, shard);
      }
      const loaded = await shard;
      if (loaded === null && shards.get(n) === shard) shards.delete(n);
      if (loaded === null || !sameStamp(loaded.directory, found.directory)) return null;
      const row = loaded.areas.find((area) => area[0] === zip);
      return row === undefined ? null : areaOf(row, loaded.directory);
    },
  };
}

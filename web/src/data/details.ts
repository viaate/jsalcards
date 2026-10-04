/**
 * Reads what the directory says about one school (details-format.ts): the
 * shard index once, then the one shard the school is in. Each file is read
 * once per page; a file that cannot be read, or does not match its format,
 * reads as nothing, and the panel shows what it has without it.
 */

import type { DirectoryStamp, SchoolId } from '../types/generated';
import {
  DETAILS_INDEX_PATH,
  KIND_FLAGS,
  SCHOOLS_PER_SHARD,
  SHARD_FILE,
  isDetailRow,
  shardOf,
} from './details-format';
import type { DetailRow } from './details-format';
import { fetchFile, fetchJson } from './files';
import type { DataFiles, Fetch } from './files';

/** A school near another, as a row lists it. */
export interface NearbyRecord {
  /** Its position in the directory. */
  readonly index: number;
  readonly id: SchoolId;
  /** Its name as the directory spells it. */
  readonly name: string;
  readonly metres: number;
  readonly lon: number;
  readonly lat: number;
}

/** One school, as the detail files give it. */
export interface SchoolRecord {
  readonly id: SchoolId;
  /** Its position in the directory (meta.json), which live files point at. */
  readonly index: number;
  /** Its name as the directory spells it. */
  readonly name: string;
  readonly private: boolean;
  readonly charter: boolean;
  readonly virtual: boolean;
  /** Its district, or null for a school outside one (most private schools). */
  readonly district: { readonly index: number; readonly id: string; readonly name: string } | null;
  readonly street: string | null;
  readonly city: string | null;
  readonly state: string;
  readonly zip: string | null;
  readonly county: string | null;
  /** Lowest and highest grade as NCES codes, or null when NCES gives either one no known code. */
  readonly grades: { readonly low: string; readonly high: string } | null;
  readonly enrollment: number | null;
  /** 10 digits. */
  readonly phone: string | null;
  /** The nearest other schools, nearest first (details-format.ts). */
  readonly nearby: readonly NearbyRecord[];
  /** The directory the record points into. */
  readonly directory: DirectoryStamp;
}

interface Shard {
  readonly first: number;
  readonly rows: readonly DetailRow[];
  readonly directory: DirectoryStamp;
}

interface ShardIndex {
  readonly firstIds: readonly string[];
  /** Each shard's file name, in the index's folder. */
  readonly files: readonly string[];
  readonly directory: DirectoryStamp;
}

const LOCAL_DATE = /^\d{4}-\d{2}-\d{2}$/;
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
export function parseShardIndex(value: unknown): ShardIndex | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  const directory = parseStamp(file.directory);
  const ids = file.first_ids;
  const names = file.files;
  if (file.schema_version !== 1 || directory === null) return null;
  if (!Array.isArray(ids) || !Array.isArray(names)) return null;
  if (file.shards !== ids.length || ids.length === 0 || names.length !== ids.length) return null;
  if (!ids.every((id) => typeof id === 'string')) return null;
  if (!names.every((name) => typeof name === 'string' && SHARD_FILE.test(name))) return null;
  return { firstIds: ids, files: names, directory };
}

/** A shard, checked row by row; null for anything else. */
export function parseShard(value: unknown): Shard | null {
  if (typeof value !== 'object' || value === null) return null;
  const file = value as Record<string, unknown>;
  const directory = parseStamp(file.directory);
  const { first, rows } = file;
  if (file.schema_version !== 1 || directory === null || !isCount(first)) return null;
  if (first % SCHOOLS_PER_SHARD !== 0 || !Array.isArray(rows)) return null;
  if (rows.length === 0 || rows.length > SCHOOLS_PER_SHARD) return null;
  if (first + rows.length > directory.schools || !rows.every(isDetailRow)) return null;
  return { first, rows, directory };
}

/** A row as a record, at its position in the directory. */
export function recordOf(row: DetailRow, index: number, directory: DirectoryStamp): SchoolRecord {
  const [id, name, flags, district, districtId, districtName, ...rest] = row;
  const [street, city, state, zip, county, low, high, enrollment, phone, nearby] = rest;
  return {
    id,
    index,
    name,
    private: (flags & KIND_FLAGS.private) !== 0,
    charter: (flags & KIND_FLAGS.charter) !== 0,
    virtual: (flags & KIND_FLAGS.virtual) !== 0,
    district:
      district === null || districtId === null || districtName === null
        ? null
        : { index: district, id: districtId, name: districtName },
    street,
    city,
    state,
    zip,
    county,
    grades: low === null || high === null ? null : { low, high },
    enrollment,
    phone,
    nearby: nearby.map(([at, nearId, nearName, metres, lon, lat]) => ({
      index: at,
      id: nearId,
      name: nearName,
      metres,
      lon,
      lat,
    })),
    directory,
  };
}

export interface DetailsSource {
  /** The school with this id, or null when this build ships no details or has no such school. */
  get(id: SchoolId): Promise<SchoolRecord | null>;
}

export function createDetailsSource(files: DataFiles, fetchImpl: Fetch = fetchFile): DetailsSource {
  let index: Promise<ShardIndex | null> | null = null;
  const shards = new Map<number, Promise<Shard | null>>();
  const readIndex = async (): Promise<ShardIndex | null> => {
    try {
      return parseShardIndex(await fetchJson(files, DETAILS_INDEX_PATH, {}, fetchImpl));
    } catch {
      return null;
    }
  };
  /** A shard, by its name in the index's folder. */
  const readShard = async (name: string): Promise<Shard | null> => {
    const base = files.url(DETAILS_INDEX_PATH);
    if (base === null) return null;
    try {
      const response = await fetchImpl(new URL(name, base).href);
      return response.ok ? parseShard((await response.json()) as unknown) : null;
    } catch {
      return null;
    }
  };
  return {
    async get(id) {
      if (!files.has(DETAILS_INDEX_PATH)) return null;
      index ??= readIndex();
      const found = await index;
      if (found === null) return null;
      const n = shardOf(found.firstIds, id);
      const name = found.files[n];
      if (name === undefined) return null;
      let shard = shards.get(n);
      if (shard === undefined) {
        shard = readShard(name);
        shards.set(n, shard);
      }
      const loaded = await shard;
      if (loaded === null || !sameStamp(loaded.directory, found.directory)) return null;
      const at = loaded.rows.findIndex((row) => row[0] === id);
      const row = loaded.rows[at];
      return row === undefined ? null : recordOf(row, loaded.first + at, loaded.directory);
    },
  };
}

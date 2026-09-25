/**
 * Builds the search index file from records. Used by
 * scripts/build-search-index.mjs and by the tests; the site never imports it.
 * See format.ts for the layout.
 */
import {
  ByteWriter,
  COORD_DECIMALS,
  COORD_PLANES,
  FORMAT_VERSION,
  GROUP_COUNT,
  GROUP_OF_KIND,
  HEADER_BYTES,
  KIND_CODES,
  MAGIC,
  SECTION_COUNT,
  Section,
  quantizeWeight,
  zigzag,
} from './format';
import { NORMALIZER_VERSION, indexTokens, tokenize } from './normalize';
import { STATES, STATE_INDEX } from './states';
import type { RecordKind, SearchRecord } from './types';

/** A record the builder refuses, with where it came from. */
export class RecordError extends Error {
  constructor(where: string, message: string) {
    super(`${where}: ${message}`);
    this.name = 'RecordError';
  }
}

const RECORD_KEYS = new Set(['kind', 'id', 'name', 'sub', 'state', 'lat', 'lon', 'weight']);
const MAX_NAME = 200;
const MAX_ID = 64;
// Control characters are exactly what this strips.
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g;
const SPACES = /\s+/g;

/** NFC, control characters to spaces, runs of whitespace to one space, trimmed. */
export function cleanText(text: string): string {
  return text.normalize('NFC').replace(CONTROL, ' ').replace(SPACES, ' ').trim();
}

/**
 * Checks one parsed JSON value against the record contract and returns it
 * with its text cleaned. `where` names it in errors, such as "schools.jsonl:12".
 */
export function validateRecord(value: unknown, where: string): SearchRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new RecordError(where, 'expected a JSON object');
  }
  const obj = value as Record<string, unknown>;
  for (const key of Object.keys(obj)) {
    if (!RECORD_KEYS.has(key)) throw new RecordError(where, `unknown field "${key}"`);
  }
  const { kind, id, name, sub, state, lat, lon, weight } = obj;
  if (typeof kind !== 'string' || !(KIND_CODES as readonly string[]).includes(kind)) {
    throw new RecordError(where, `kind must be one of ${KIND_CODES.join(', ')}`);
  }
  if (typeof id !== 'string' || id.length === 0 || id.length > MAX_ID || /[\s]/.test(id)) {
    throw new RecordError(where, `id must be 1 to ${String(MAX_ID)} characters without spaces`);
  }
  if (typeof name !== 'string') throw new RecordError(where, 'name must be a string');
  const cleanName = cleanText(name);
  if (cleanName.length === 0 || cleanName.length > MAX_NAME) {
    throw new RecordError(where, `name must be 1 to ${String(MAX_NAME)} characters`);
  }
  if (tokenize(cleanName).length === 0) {
    throw new RecordError(where, `name "${cleanName}" has no letters or digits to search by`);
  }
  if (typeof sub !== 'string') throw new RecordError(where, 'sub must be a string');
  const cleanSub = cleanText(sub);
  if (cleanSub.length > MAX_NAME) {
    throw new RecordError(where, `sub must be at most ${String(MAX_NAME)} characters`);
  }
  if (typeof state !== 'string' || !STATE_INDEX.has(state)) {
    throw new RecordError(where, 'state must be a USPS code such as "PA"');
  }
  if (typeof lat !== 'number' || !Number.isFinite(lat) || lat < -90 || lat > 90) {
    throw new RecordError(where, 'lat must be a number from -90 to 90');
  }
  if (typeof lon !== 'number' || !Number.isFinite(lon) || lon < -180 || lon > 180) {
    throw new RecordError(where, 'lon must be a number from -180 to 180');
  }
  if (typeof weight !== 'number' || !Number.isFinite(weight) || weight < 0) {
    throw new RecordError(where, 'weight must be a finite number of 0 or more');
  }
  return {
    kind: kind as RecordKind,
    id,
    name: cleanName,
    sub: cleanSub,
    state,
    lat,
    lon,
    weight,
  };
}

const STATE_WORDS = new Set<string>();
for (const [code, name] of STATES) {
  STATE_WORDS.add(code.toLowerCase());
  STATE_WORDS.add(tokenize(name).join(' '));
}

/**
 * UTF-16 length of the part of a sub that names a place: "Lancaster, PA"
 * gives 9 ("Lancaster"). Trailing comma-separated state codes or names are
 * left out, but never the first part of a sub with several ("Washington, DC"
 * keeps "Washington"); a sub that is only a state has no place part.
 */
export function placeLength(sub: string): number {
  const parts = sub.split(',');
  let keep = parts.length;
  const isState = (part: string): boolean => STATE_WORDS.has(tokenize(part).join(' '));
  if (keep === 1) return isState(sub) ? 0 : sub.trimEnd().length;
  while (keep > 1 && isState(parts[keep - 1] ?? '')) keep--;
  return parts.slice(0, keep).join(',').trimEnd().length;
}

export interface EncodeStats {
  readonly records: number;
  readonly byKind: Readonly<Record<RecordKind, number>>;
  readonly subs: number;
  readonly tokens: number;
  /** Record-token pairs the worker will index (names only). */
  readonly postings: number;
  /** Uncompressed bytes per section. */
  readonly sections: Readonly<Record<string, number>>;
  readonly bytes: number;
}

function compareCodeUnits(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

const DIGITS = /^\d+$/;

function isHighSurrogate(c: number): boolean {
  return c >= 0xd800 && c <= 0xdbff;
}

function commonPrefix(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let l = 0;
  while (l < max && a.charCodeAt(l) === b.charCodeAt(l)) l++;
  return l;
}

/** The one TextEncoder method used here, typed without the DOM library. */
interface Utf8Encoder {
  encode(input: string): Uint8Array;
}

/** One id in the ids section's encoding (see format.ts). */
function writeId(w: ByteWriter, prev: string, id: string, enc: Utf8Encoder): void {
  if (prev.length === id.length && DIGITS.test(id) && DIGITS.test(prev)) {
    const step = Number(id) - Number(prev);
    if (step > 0 && step <= 0x7fffffff && Number.isSafeInteger(Number(id))) {
      w.varint(step);
      return;
    }
  }
  let l = commonPrefix(prev, id);
  if (l > 0 && l < id.length && isHighSurrogate(id.charCodeAt(l - 1))) l--;
  const suffix = enc.encode(id.slice(l));
  w.varint(0);
  w.varint(l);
  w.varint(suffix.length);
  w.bytes(suffix);
}

/**
 * Encodes records into an (uncompressed) index. Throws RecordError on
 * duplicate ids within a kind.
 */
export function encodeIndex(input: readonly SearchRecord[]): {
  bytes: Uint8Array;
  stats: EncodeStats;
} {
  const kindCode = new Map<string, number>(KIND_CODES.map((k, i) => [k, i]));
  const byKind: Record<RecordKind, number> = { school: 0, district: 0, city: 0, zip: 0 };
  const seen = new Set<string>();
  for (const r of input) {
    const key = `${r.kind}\u0000${r.id}`;
    if (seen.has(key)) throw new RecordError(`${r.kind} ${r.id}`, 'duplicate id');
    seen.add(key);
    byKind[r.kind]++;
  }

  const group = (r: SearchRecord): number => GROUP_OF_KIND[kindCode.get(r.kind) ?? 0] ?? 0;
  const records = [...input].sort(
    (a, b) =>
      group(a) - group(b) ||
      compareCodeUnits(a.id, b.id) ||
      (kindCode.get(a.kind) ?? 0) - (kindCode.get(b.kind) ?? 0),
  );
  const groupCounts = new Array<number>(GROUP_COUNT).fill(0);
  for (const r of records) groupCounts[group(r)] = (groupCounts[group(r)] ?? 0) + 1;

  // Unique subs in code-unit order; only schools and districts index places.
  const subList = [...new Set(records.map((r) => r.sub))].sort(compareCodeUnits);
  const subIndex = new Map(subList.map((s, i) => [s, i]));
  const placed = new Set<string>();
  for (const r of records) if (group(r) === 0) placed.add(r.sub);
  const subLoc = subList.map((s) => (placed.has(s) ? placeLength(s) : 0));

  // Dictionary: every token a name or place part is indexed under.
  const dict = new Set<string>();
  let postings = 0;
  for (const r of records) {
    const toks = indexTokens(tokenize(r.name));
    postings += toks.length;
    for (const t of toks) dict.add(t);
  }
  subList.forEach((s, i) => {
    const len = subLoc[i] ?? 0;
    if (len > 0) for (const t of indexTokens(tokenize(s.slice(0, len)))) dict.add(t);
  });
  const tokens = [...dict].sort(compareCodeUnits);

  const enc = new TextEncoder();
  const sections: Uint8Array[] = new Array<Uint8Array>(SECTION_COUNT);

  sections[Section.names] = enc.encode(records.map((r) => `${r.name}\n`).join(''));
  sections[Section.subs] = enc.encode(subList.map((s) => `${s}\n`).join(''));

  const subLocW = new ByteWriter();
  for (const len of subLoc) subLocW.varint(len);
  sections[Section.subLoc] = subLocW.finish();

  const recordSubW = new ByteWriter();
  let prevSub = 0;
  for (const r of records) {
    const s = subIndex.get(r.sub) ?? 0;
    recordSubW.varint(zigzag(s - prevSub));
    prevSub = s;
  }
  sections[Section.recordSub] = recordSubW.finish();

  const kindState = new Uint8Array(records.length);
  records.forEach((r, i) => {
    kindState[i] = ((kindCode.get(r.kind) ?? 0) << 6) | (STATE_INDEX.get(r.state) ?? 0);
  });
  sections[Section.kindState] = kindState;

  const n = records.length;
  const weight = new Uint8Array(n * 2);
  records.forEach((r, i) => {
    const q = quantizeWeight(r.weight);
    weight[i] = q & 0xff;
    weight[n + i] = q >>> 8;
  });
  sections[Section.weight] = weight;

  // Coordinates: residuals from the last record in the same place.
  const scale = 10 ** COORD_DECIMALS;
  const planes = new Uint8Array(COORD_PLANES * 2 * n);
  const lastLat = new Int32Array(subList.length);
  const lastLon = new Int32Array(subList.length);
  const seenSub = new Uint8Array(subList.length);
  let prevLat = 0;
  let prevLon = 0;
  const plane = 2 * n;
  const limit = 2 ** (8 * COORD_PLANES);
  records.forEach((r, i) => {
    const lat = Math.round(r.lat * scale);
    const lon = Math.round(r.lon * scale);
    const s = subIndex.get(r.sub) ?? 0;
    const refLat = seenSub[s] ? (lastLat[s] ?? 0) : prevLat;
    const refLon = seenSub[s] ? (lastLon[s] ?? 0) : prevLon;
    const dLat = zigzag(lat - refLat);
    const dLon = zigzag(lon - refLon);
    if (dLat >= limit || dLon >= limit)
      throw new Error('Snowlight search: coordinate step too large');
    for (let p = 0; p < COORD_PLANES; p++) {
      planes[p * plane + 2 * i] = (dLat >>> (8 * p)) & 0xff;
      planes[p * plane + 2 * i + 1] = (dLon >>> (8 * p)) & 0xff;
    }
    lastLat[s] = lat;
    lastLon[s] = lon;
    seenSub[s] = 1;
    prevLat = lat;
    prevLon = lon;
  });
  sections[Section.coords] = planes;

  // Ids: numeric steps where possible, else front-coded against the previous id.
  let idFlags = 0;
  const idW = new ByteWriter();
  let start = 0;
  for (let g = 0; g < GROUP_COUNT; g++) {
    const end = start + (groupCounts[g] ?? 0);
    const slice = records.slice(start, end);
    if (slice.every((r) => r.id === r.name)) idFlags |= 1 << g;
    else {
      let prev = '';
      for (const r of slice) {
        writeId(idW, prev, r.id, enc);
        prev = r.id;
      }
    }
    start = end;
  }
  sections[Section.ids] = idW.finish();

  const shared = new Uint8Array(tokens.length);
  const suffixes: string[] = [];
  let prev = '';
  tokens.forEach((t, i) => {
    let l = commonPrefix(prev, t);
    // Never split a surrogate pair between the shared prefix and the suffix.
    if (l > 0 && l < t.length && isHighSurrogate(t.charCodeAt(l - 1))) l--;
    if (l > 255) l = 255;
    shared[i] = l;
    suffixes.push(`${t.slice(l)}\n`);
    prev = t;
  });
  sections[Section.dictShared] = shared;
  sections[Section.dictSuffix] = enc.encode(suffixes.join(''));

  const out = new ByteWriter();
  out.u32(MAGIC);
  out.u16(FORMAT_VERSION);
  out.u16(NORMALIZER_VERSION);
  out.u32(records.length);
  out.u32(subList.length);
  out.u32(tokens.length);
  for (let g = 0; g < GROUP_COUNT; g++) out.u32(groupCounts[g] ?? 0);
  out.u8(COORD_DECIMALS);
  out.u8(idFlags);
  out.u16(SECTION_COUNT);
  out.u32(0);
  if (out.length !== HEADER_BYTES) throw new Error('Snowlight search: header size mismatch');
  const tableAt = out.length;
  for (let s = 0; s < SECTION_COUNT; s++) {
    out.u32(0);
    out.u32(0);
  }
  const sectionBytes: Record<string, number> = {};
  const names = Object.keys(Section);
  for (let s = 0; s < SECTION_COUNT; s++) {
    const data = sections[s] ?? new Uint8Array(0);
    out.patchU32(tableAt + s * 8, out.length);
    out.patchU32(tableAt + s * 8 + 4, data.length);
    out.bytes(data);
    sectionBytes[names[s] ?? String(s)] = data.length;
  }
  const bytes = out.finish();
  return {
    bytes,
    stats: {
      records: records.length,
      byKind,
      subs: subList.length,
      tokens: tokens.length,
      postings,
      sections: sectionBytes,
      bytes: bytes.length,
    },
  };
}

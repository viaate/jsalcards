/**
 * Loads an index file (see format.ts) into the structures queries run on.
 *
 * The file carries display text and the token dictionary but no postings:
 * the worker re-tokenizes every name with the same rules the builder used
 * (normalize.ts) and builds the postings itself, which keeps the download
 * small. Names are scanned in bulk and tokens are found by hashing their
 * character codes, so loading makes no string per token.
 *
 * Inside each group, records are ranked by weight (heaviest first, ties in
 * file order), and every per-group array is indexed by that rank, so the
 * first matches found in rank order are the heaviest.
 *
 * Each step is its own small function: the worker loads once, so this code
 * always runs cold, and small functions reach optimized code sooner.
 */
import {
  ByteReader,
  COORD_PLANES,
  FORMAT_VERSION,
  GROUP_COUNT,
  GROUP_OF_KIND,
  HEADER_BYTES,
  KIND_CODES,
  MAGIC,
  MAX_WEIGHT_CODE,
  SECTION_COUNT,
  Section,
  unzigzag,
} from './format';
import {
  ABBREVIATIONS,
  MAX_TOKEN_LENGTH,
  NORMALIZER_VERSION,
  expandTokens,
  expandedLength,
  scanAscii,
  tokenize,
} from './normalize';
import type { AbbreviationRule, TokenSink } from './normalize';
import { stateCode } from './states';
import { Dictionary, TokenTrie } from './trie';
import type { RecordKind } from './types';

/** One result group's records, in rank order. */
export interface GroupData {
  readonly size: number;
  /** Words in a bitset over this group's ranks. */
  readonly words: number;
  /** Rank to file record index. */
  readonly fileIndex: Uint32Array;
  /** Rank to kind << 6 | state index. */
  readonly kindState: Uint8Array;
  /** Rank to the word count of the name with abbreviations spelled out. */
  readonly canon: Uint8Array;
  /** Token id to the start of its ranks in namePost (length tokens + 1). */
  readonly nameOff: Uint32Array;
  /** Ranks of records whose name has each token. */
  readonly namePost: Uint32Array;
  /** Sub index to the start of its ranks in subRanks, or null when places are not searched. */
  readonly subOff: Uint32Array | null;
  readonly subRanks: Uint32Array | null;
}

/** A record as results show it. */
export interface RecordView {
  readonly kind: RecordKind;
  readonly id: string;
  readonly name: string;
  readonly sub: string;
  readonly state: string;
  readonly lat: number;
  readonly lon: number;
}

export class IndexFormatError extends Error {
  constructor(message: string) {
    super(`Snowlight search: ${message}`);
    this.name = 'IndexFormatError';
  }
}

interface IndexParts {
  readonly recordCount: number;
  readonly dict: Dictionary;
  readonly trie: TokenTrie;
  readonly groups: readonly GroupData[];
  readonly locOff: Uint32Array;
  readonly locSubs: Uint32Array;
  readonly names: string;
  readonly nameStart: Uint32Array;
  readonly subs: readonly string[];
  readonly recordSub: Uint32Array;
  readonly kindStateFile: Uint8Array;
  readonly lat: Int32Array;
  readonly lon: Int32Array;
  readonly coordScale: number;
  readonly ids: IdColumn;
}

export class SearchIndex {
  readonly recordCount: number;
  readonly dict: Dictionary;
  readonly trie: TokenTrie;
  readonly groups: readonly GroupData[];
  /** Token id to the start of its subs in locSubs (length tokens + 1). */
  readonly locOff: Uint32Array;
  /** Subs whose place part has each token. */
  readonly locSubs: Uint32Array;
  private readonly parts: IndexParts;

  constructor(parts: IndexParts) {
    this.parts = parts;
    this.recordCount = parts.recordCount;
    this.dict = parts.dict;
    this.trie = parts.trie;
    this.groups = parts.groups;
    this.locOff = parts.locOff;
    this.locSubs = parts.locSubs;
  }

  name(file: number): string {
    const { names, nameStart } = this.parts;
    return names.slice(nameStart[file] ?? 0, (nameStart[file + 1] ?? 1) - 1);
  }

  record(file: number): RecordView {
    const p = this.parts;
    const ks = p.kindStateFile[file] ?? 0;
    const name = this.name(file);
    return {
      kind: KIND_CODES[ks >>> 6] ?? 'school',
      id: p.ids.get(file) ?? name,
      name,
      sub: p.subs[p.recordSub[file] ?? 0] ?? '',
      state: stateCode(ks & 63),
      lat: (p.lat[file] ?? 0) / p.coordScale,
      lon: (p.lon[file] ?? 0) / p.coordScale,
    };
  }
}

interface Header {
  readonly recordCount: number;
  readonly subCount: number;
  readonly tokenCount: number;
  readonly groupCounts: readonly number[];
  readonly coordDecimals: number;
  readonly idFlags: number;
  readonly sections: readonly (readonly [number, number])[];
}

/** Throws IndexFormatError unless `bytes` starts like an index this code reads. */
function readHeader(bytes: Uint8Array): Header {
  if (bytes.length < HEADER_BYTES + SECTION_COUNT * 8) {
    throw new IndexFormatError('index file is truncated');
  }
  const r = new ByteReader(bytes);
  if (r.u32() !== MAGIC) throw new IndexFormatError('not a search index file');
  const version = r.u16();
  if (version !== FORMAT_VERSION) {
    throw new IndexFormatError(`index format ${String(version)} is not supported`);
  }
  const normalizer = r.u16();
  if (normalizer !== NORMALIZER_VERSION) {
    throw new IndexFormatError(
      `index was built with tokenizer ${String(normalizer)}, this code uses ${String(NORMALIZER_VERSION)}`,
    );
  }
  const recordCount = r.u32();
  const subCount = r.u32();
  const tokenCount = r.u32();
  const groupCounts: number[] = [];
  for (let g = 0; g < GROUP_COUNT; g++) groupCounts.push(r.u32());
  const coordDecimals = r.u8();
  const idFlags = r.u8();
  const sectionCount = r.u16();
  r.u32();
  if (sectionCount !== SECTION_COUNT) throw new IndexFormatError('unexpected section count');
  if (groupCounts.reduce((a, b) => a + b, 0) !== recordCount) {
    throw new IndexFormatError('group sizes do not add up');
  }
  if (coordDecimals > 7) throw new IndexFormatError('unexpected coordinate precision');
  const sections: (readonly [number, number])[] = [];
  for (let s = 0; s < SECTION_COUNT; s++) {
    const offset = r.u32();
    const length = r.u32();
    if (offset + length > bytes.length) throw new IndexFormatError('section out of bounds');
    sections.push([offset, offset + length]);
  }
  return { recordCount, subCount, tokenCount, groupCounts, coordDecimals, idFlags, sections };
}

/** Offsets just past each '\n' in a decoded string, with 0 first; expects `count` lines. */
function lineStarts(text: string, count: number, what: string): Uint32Array {
  const starts = new Uint32Array(count + 1);
  let pos = 0;
  for (let i = 0; i < count; i++) {
    const nl = text.indexOf('\n', pos);
    if (nl < 0) throw new IndexFormatError(`${what} section has too few entries`);
    pos = nl + 1;
    starts[i + 1] = pos;
  }
  if (pos !== text.length) throw new IndexFormatError(`${what} section has extra data`);
  return starts;
}

/** The front-coded dictionary sections, as one flat character array. */
function readDictionary(shared: Uint8Array, suffixes: Uint8Array, count: number): Dictionary {
  if (shared.length !== count) throw new IndexFormatError('dictionary has the wrong size');
  let total = 0;
  for (let i = 0; i < count; i++) total += shared[i] ?? 0;
  // UTF-8 suffixes never have fewer bytes than UTF-16 units, so this is enough.
  const chars = new Uint16Array(total + suffixes.length);
  const offsets = new Uint32Array(count + 1);
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let pos = 0;
  let at = 0;
  let prevStart = 0;
  let prevLen = 0;
  for (let i = 0; i < count; i++) {
    const l = shared[i] ?? 0;
    if (l > prevLen) throw new IndexFormatError('dictionary is corrupt');
    chars.copyWithin(at, prevStart, prevStart + l);
    const start = at;
    at += l;
    let end = pos;
    let ascii = true;
    while (end < suffixes.length && suffixes[end] !== 0x0a) {
      if ((suffixes[end] ?? 0) >= 0x80) ascii = false;
      end++;
    }
    if (end >= suffixes.length) throw new IndexFormatError('dictionary is corrupt');
    if (ascii) {
      for (let b = pos; b < end; b++) chars[at++] = suffixes[b] ?? 0;
    } else {
      const text = decoder.decode(suffixes.subarray(pos, end));
      for (let k = 0; k < text.length; k++) chars[at++] = text.charCodeAt(k);
    }
    pos = end + 1;
    offsets[i + 1] = at;
    prevStart = start;
    prevLen = at - start;
  }
  if (pos !== suffixes.length) throw new IndexFormatError('dictionary has extra data');
  return new Dictionary(chars.slice(0, at), offsets);
}

/**
 * Token ids by content: open addressing on an FNV-1a hash of the character
 * codes, so a token is found from a code buffer without making a string.
 *
 * Each slot is four int32s, one cache line holds four slots: the hash, the
 * token id (-1 for empty), the length, and the first and last characters.
 * A probe that matches all four is the token, unless another token shares
 * all four; only for those is every character compared.
 */
/** Token ids fit in the low 20 bits of a slot's second word. */
const MAX_TOKENS = 1 << 20;
/** Slot flag: another token has the same hash and length. */
const AMBIGUOUS = 1 << 30;

/**
 * Token ids by content: open addressing on an FNV-1a hash of the character
 * codes, so a token is found from a code buffer without making a string.
 *
 * A slot is two int32s: the hash, then the id (low 20 bits), the length
 * (next 8) and the AMBIGUOUS flag; -1 when empty. A probe matching hash and
 * length is the token, unless another token shares both; only then are the
 * characters compared.
 */
export class TokenTable {
  private readonly slots: Int32Array;
  private readonly mask: number;
  private readonly chars: Uint16Array;
  private readonly offsets: Uint32Array;

  constructor(dict: Dictionary) {
    const { chars, offsets, count } = dict;
    if (count >= MAX_TOKENS) throw new IndexFormatError('dictionary is too large');
    this.chars = chars;
    this.offsets = offsets;
    let size = 1024;
    while (size < count * 1.5) size *= 2;
    const slots = (this.slots = new Int32Array(size * 2));
    for (let i = 1; i < slots.length; i += 2) slots[i] = -1;
    const mask = (this.mask = size - 1);
    for (let id = 0; id < count; id++) {
      const start = offsets[id] ?? 0;
      const end = offsets[id + 1] ?? 0;
      let h = 0x811c9dc5;
      for (let i = start; i < end; i++) h = Math.imul(h ^ (chars[i] ?? 0), 0x01000193);
      const lenBits = (end - start) << 20;
      // Tokens with the same hash probe from the same slot, so any earlier
      // token sharing this one's hash is passed on the way to a free slot.
      let ambiguous = 0;
      for (let slot = h & mask; ; slot = (slot + 1) & mask) {
        const at = slot * 2;
        const meta = slots[at + 1] ?? -1;
        if (meta < 0) {
          slots[at] = h;
          slots[at + 1] = id | lenBits | ambiguous;
          break;
        }
        if (slots[at] === h && (meta & 0xff00000) === lenBits) {
          slots[at + 1] = meta | AMBIGUOUS;
          ambiguous = AMBIGUOUS;
        }
      }
    }
  }

  /**
   * Id of the token spelled by codes[0, length), or -1. For names, whose
   * tokens are all in the dictionary: a word that is not may, with odds of
   * about one in 2^32 per token, match one that is.
   */
  find(codes: Uint16Array, length: number): number {
    let h = 0x811c9dc5;
    for (let i = 0; i < length; i++) h = Math.imul(h ^ (codes[i] ?? 0), 0x01000193);
    const lenBits = length << 20;
    const { slots, mask } = this;
    for (let slot = h & mask; ; slot = (slot + 1) & mask) {
      const at = slot * 2;
      const meta = slots[at + 1] ?? -1;
      if (meta < 0) return -1;
      if (slots[at] !== h || (meta & 0xff00000) !== lenBits) continue;
      const id = meta & (MAX_TOKENS - 1);
      if ((meta & AMBIGUOUS) === 0 || this.same(id, codes, length)) return id;
    }
  }

  /**
   * Id of a token string, or -1, comparing every character, so a word that
   * is not in the dictionary is never mistaken for one that is.
   */
  findString(token: string, scratch: Uint16Array): number {
    if (token.length > scratch.length) return -1;
    for (let i = 0; i < token.length; i++) scratch[i] = token.charCodeAt(i);
    let h = 0x811c9dc5;
    for (let i = 0; i < token.length; i++) h = Math.imul(h ^ (scratch[i] ?? 0), 0x01000193);
    const { slots, mask } = this;
    for (let slot = h & mask; ; slot = (slot + 1) & mask) {
      const at = slot * 2;
      const meta = slots[at + 1] ?? -1;
      if (meta < 0) return -1;
      const id = meta & (MAX_TOKENS - 1);
      if (slots[at] === h && this.same(id, scratch, token.length)) return id;
    }
  }

  private same(id: number, codes: Uint16Array, length: number): boolean {
    const start = this.offsets[id] ?? 0;
    if ((this.offsets[id + 1] ?? 0) - start !== length) return false;
    for (let i = 0; i < length; i++) if (this.chars[start + i] !== codes[i]) return false;
    return true;
  }
}

/**
 * Appends the indexed token ids of texts to one growing list, as the
 * builder indexes them: tokens, repeats dropped, plus the abbreviation
 * expansions of normalize.ts run over ids with the same rules.
 */
class IdTokenizer implements TokenSink {
  data = new Int32Array(1 << 16);
  length = 0;
  private readonly table: TokenTable;
  private readonly rules: (AbbreviationRule<number>[] | undefined)[];
  /** 1 for token ids that start some abbreviation rule. */
  private readonly startsRule: Uint8Array;
  private readonly buf = new Uint16Array(MAX_TOKEN_LENGTH);
  private readonly scratch = new Uint16Array(MAX_TOKEN_LENGTH);
  private readonly expanded: number[] = [];

  constructor(table: TokenTable, tokenCount: number) {
    this.table = table;
    this.rules = new Array<AbbreviationRule<number>[] | undefined>(tokenCount);
    this.startsRule = new Uint8Array(tokenCount);
    for (const rule of ABBREVIATIONS) {
      const short = rule.short.map((t) => table.findString(t, this.scratch));
      const long = rule.long.map((t) => table.findString(t, this.scratch));
      // A rule whose abbreviation is not in the dictionary matches no name.
      if (short.some((id) => id < 0)) continue;
      const first = short[0] ?? 0;
      const list = this.rules[first] ?? (this.rules[first] = []);
      list.push({ short, long });
      this.startsRule[first] = 1;
    }
  }

  token(chars: Uint16Array, length: number): void {
    this.push(this.table.find(chars, length));
  }

  private push(id: number): void {
    if (this.length === this.data.length) {
      const next = new Int32Array(this.data.length * 2);
      next.set(this.data);
      this.data = next;
    }
    this.data[this.length++] = id;
  }

  private readonly rulesFor = (id: number): readonly AbbreviationRule<number>[] | undefined =>
    this.rules[id];

  /**
   * Appends the indexed token ids of text[start, end) and returns the
   * expanded word count. Throws when a token is missing from the dictionary.
   */
  add(text: string, start: number, end: number): number {
    const begin = this.length;
    if (!scanAscii(text, start, end, this.buf, this)) {
      this.length = begin;
      for (const t of tokenize(text.slice(start, end))) {
        this.push(this.table.findString(t, this.scratch));
      }
    }
    const data = this.data;
    const stop = this.length;
    let abbreviated = false;
    let repeated = false;
    for (let i = begin; i < stop; i++) {
      const id = data[i] ?? -1;
      if (id < 0) {
        throw new IndexFormatError(
          `a token of "${text.slice(start, end)}" is missing from the dictionary`,
        );
      }
      if (this.startsRule[id] === 1) abbreviated = true;
      for (let j = begin; j < i; j++) if (data[j] === id) repeated = true;
    }
    const count = stop - begin;
    if (!abbreviated) {
      // No rule can match: expandTokens reduces to dropping repeats and
      // expandedLength to the token count.
      if (repeated) {
        let w = begin;
        for (let i = begin; i < stop; i++) {
          const id = data[i] ?? 0;
          let seen = false;
          for (let j = begin; j < w; j++) if (data[j] === id) seen = true;
          if (!seen) data[w++] = id;
        }
        this.length = w;
      }
      return Math.min(count, 255);
    }
    const expanded = this.expanded;
    expanded.length = 0;
    expandTokens(data, begin, stop, this.rulesFor, expanded);
    const words = expandedLength(data, begin, stop, this.rulesFor);
    this.length = begin;
    for (const id of expanded) {
      if (id < 0) {
        throw new IndexFormatError('an abbreviation expansion is missing from the dictionary');
      }
      this.push(id);
    }
    return words;
  }
}

function readVarints(bytes: Uint8Array, count: number, what: string): Uint32Array {
  const out = new Uint32Array(count);
  const r = new ByteReader(bytes);
  for (let i = 0; i < count; i++) out[i] = r.varint();
  if (!r.atEnd()) throw new IndexFormatError(`${what} section has extra data`);
  return out;
}

function readRecordSubs(bytes: Uint8Array, n: number, subCount: number): Uint32Array {
  const deltas = readVarints(bytes, n, 'sub');
  const out = new Uint32Array(n);
  let prev = 0;
  for (let i = 0; i < n; i++) {
    prev += unzigzag(deltas[i] ?? 0);
    if (prev < 0 || prev >= subCount) throw new IndexFormatError('record sub out of range');
    out[i] = prev;
  }
  return out;
}

function readCoords(
  planes: Uint8Array,
  n: number,
  recordSub: Uint32Array,
  subCount: number,
): { lat: Int32Array; lon: Int32Array } {
  const plane = 2 * n;
  if (planes.length !== COORD_PLANES * plane) {
    throw new IndexFormatError('coordinate section has the wrong size');
  }
  const lat = new Int32Array(n);
  const lon = new Int32Array(n);
  const lastLat = new Int32Array(subCount);
  const lastLon = new Int32Array(subCount);
  const seen = new Uint8Array(subCount);
  let prevLat = 0;
  let prevLon = 0;
  for (let i = 0; i < n; i++) {
    let dLat = 0;
    let dLon = 0;
    for (let p = COORD_PLANES - 1; p >= 0; p--) {
      dLat = dLat * 256 + (planes[p * plane + 2 * i] ?? 0);
      dLon = dLon * 256 + (planes[p * plane + 2 * i + 1] ?? 0);
    }
    const s = recordSub[i] ?? 0;
    const la = (seen[s] === 1 ? (lastLat[s] ?? 0) : prevLat) + unzigzag(dLat);
    const lo = (seen[s] === 1 ? (lastLon[s] ?? 0) : prevLon) + unzigzag(dLon);
    lat[i] = la;
    lon[i] = lo;
    lastLat[s] = la;
    lastLon[s] = lo;
    seen[s] = 1;
    prevLat = la;
    prevLon = lo;
  }
  return { lat, lon };
}

const DIGITS = /^\d+$/;

/** Text of bytes[start, end): ASCII by hand (ids are short), anything else by `decoder`. */
function decodeShort(bytes: Uint8Array, start: number, end: number, decoder: TextDecoder): string {
  let s = '';
  for (let i = start; i < end; i++) {
    const b = bytes[i] ?? 0;
    if (b >= 0x80) return decoder.decode(bytes.subarray(start, end));
    s += String.fromCharCode(b);
  }
  return s;
}

/** Ids are decoded on demand, from the nearest of these checkpoints. */
const ID_CHECKPOINT = 64;

/**
 * The ids section, with a checkpoint every ID_CHECKPOINT records of each
 * group: the byte position of the record's entry and the id before it.
 * Loading reads every entry once but makes strings only where an entry is
 * front-coded or a checkpoint falls, so most numeric ids never become
 * strings until a result shows them.
 */
class IdColumn {
  private readonly bytes: Uint8Array;
  private readonly header: Header;
  private readonly decoder = new TextDecoder('utf-8', { fatal: true });
  private readonly groupStart: number[] = [];
  private readonly checkpointStart: number[] = [];
  private readonly positions: number[] = [];
  private readonly previous: string[] = [];

  constructor(bytes: Uint8Array, header: Header) {
    this.bytes = bytes;
    this.header = header;
    const r = new ByteReader(bytes);
    let file = 0;
    for (let g = 0; g < GROUP_COUNT; g++) {
      const count = header.groupCounts[g] ?? 0;
      this.groupStart.push(file);
      this.checkpointStart.push(this.positions.length);
      if ((header.idFlags & (1 << g)) === 0) {
        let prev = '';
        let prevNumber = NaN;
        let stale = false; // prev lags prevNumber
        for (let i = 0; i < count; i++) {
          if (i % ID_CHECKPOINT === 0) {
            if (stale) {
              prev = String(prevNumber).padStart(prev.length, '0');
              stale = false;
            }
            this.positions.push(r.pos);
            this.previous.push(prev);
          }
          const step = r.varint();
          if (step > 0) {
            if (Number.isNaN(prevNumber)) throw new IndexFormatError('ids section is corrupt');
            prevNumber += step;
            stale = true;
          } else {
            if (stale) {
              prev = String(prevNumber).padStart(prev.length, '0');
              stale = false;
            }
            prev = this.literal(r, prev);
            prevNumber = DIGITS.test(prev) ? Number(prev) : NaN;
          }
        }
      }
      file += count;
    }
    if (!r.atEnd()) throw new IndexFormatError('ids section has extra data');
  }

  /** Reads a front-coded entry (after its 0 marker) following `prev`. */
  private literal(r: ByteReader, prev: string): string {
    const l = r.varint();
    const len = r.varint();
    if (l > prev.length || r.pos + len > this.bytes.length) {
      throw new IndexFormatError('ids section is corrupt');
    }
    const id = prev.slice(0, l) + decodeShort(this.bytes, r.pos, r.pos + len, this.decoder);
    r.pos += len;
    return id;
  }

  /** The id of a file record, or undefined when its group's ids are its names. */
  get(file: number): string | undefined {
    let g = GROUP_COUNT - 1;
    while (g > 0 && file < (this.groupStart[g] ?? 0)) g--;
    if ((this.header.idFlags & (1 << g)) !== 0) return undefined;
    const i = file - (this.groupStart[g] ?? 0);
    const c = (this.checkpointStart[g] ?? 0) + Math.floor(i / ID_CHECKPOINT);
    const r = new ByteReader(this.bytes);
    r.pos = this.positions[c] ?? 0;
    let id = this.previous[c] ?? '';
    for (let k = i - (i % ID_CHECKPOINT); k <= i; k++) {
      const step = r.varint();
      id = step > 0 ? String(Number(id) + step).padStart(id.length, '0') : this.literal(r, id);
    }
    return id;
  }
}

function tokenizeNames(
  names: string,
  nameStart: Uint32Array,
  n: number,
  tokenizer: IdTokenizer,
): { fwd: Int32Array; fwdStart: Uint32Array; canon: Uint8Array } {
  const fwdStart = new Uint32Array(n + 1);
  const canon = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    canon[i] = tokenizer.add(names, nameStart[i] ?? 0, (nameStart[i + 1] ?? 1) - 1);
    fwdStart[i + 1] = tokenizer.length;
  }
  return { fwd: tokenizer.data, fwdStart, canon };
}

/** File indexes of a group in rank order: heaviest first, ties in file order. */
function rankGroup(
  weightBytes: Uint8Array,
  n: number,
  kindState: Uint8Array,
  g: number,
  from: number,
  to: number,
): Uint32Array {
  const buckets = new Uint32Array(MAX_WEIGHT_CODE + 2);
  for (let i = from; i < to; i++) {
    if (GROUP_OF_KIND[(kindState[i] ?? 0) >>> 6] !== g) {
      throw new IndexFormatError('record stored in the wrong group');
    }
    const w = (weightBytes[i] ?? 0) | ((weightBytes[n + i] ?? 0) << 8);
    if (w > MAX_WEIGHT_CODE) throw new IndexFormatError('weight out of range');
    const b = MAX_WEIGHT_CODE - w;
    buckets[b + 1] = (buckets[b + 1] ?? 0) + 1;
  }
  for (let b = 0; b <= MAX_WEIGHT_CODE; b++) {
    buckets[b + 1] = (buckets[b + 1] ?? 0) + (buckets[b] ?? 0);
  }
  const fileIndex = new Uint32Array(to - from);
  for (let i = from; i < to; i++) {
    const b = MAX_WEIGHT_CODE - ((weightBytes[i] ?? 0) | ((weightBytes[n + i] ?? 0) << 8));
    const rank = buckets[b] ?? 0;
    buckets[b] = rank + 1;
    fileIndex[rank] = i;
  }
  return fileIndex;
}

/**
 * CSR postings of a group: for each token, the ranks whose names have it.
 * Records are read in file order, which is sequential in memory; the ranks
 * of one token end up in file order too, which is fine because queries only
 * set bits from them.
 */
function buildPostings(
  from: number,
  to: number,
  rankOf: Uint32Array,
  fwd: Int32Array,
  fwdStart: Uint32Array,
  tokenCount: number,
): { off: Uint32Array; post: Uint32Array } {
  const off = new Uint32Array(tokenCount + 1);
  const first = fwdStart[from] ?? 0;
  const last = fwdStart[to] ?? 0;
  for (let p = first; p < last; p++) {
    const t = (fwd[p] ?? 0) + 1;
    off[t] = (off[t] ?? 0) + 1;
  }
  for (let t = 0; t < tokenCount; t++) off[t + 1] = (off[t + 1] ?? 0) + (off[t] ?? 0);
  const post = new Uint32Array(off[tokenCount] ?? 0);
  const cursor = off.slice(0, tokenCount);
  for (let f = from; f < to; f++) {
    const rank = rankOf[f] ?? 0;
    const stop = fwdStart[f + 1] ?? 0;
    for (let p = fwdStart[f] ?? 0; p < stop; p++) {
      const t = fwd[p] ?? 0;
      post[cursor[t] ?? 0] = rank;
      cursor[t] = (cursor[t] ?? 0) + 1;
    }
  }
  return { off, post };
}

/** For each key, the positions whose key it is, in order (a counting sort). */
function invert(keys: Uint32Array, keyCount: number): { off: Uint32Array; values: Uint32Array } {
  const off = new Uint32Array(keyCount + 1);
  for (const key of keys) off[key + 1] = (off[key + 1] ?? 0) + 1;
  for (let k = 0; k < keyCount; k++) off[k + 1] = (off[k + 1] ?? 0) + (off[k] ?? 0);
  const values = new Uint32Array(keys.length);
  const cursor = off.slice(0, keyCount);
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i] ?? 0;
    values[cursor[k] ?? 0] = i;
    cursor[k] = (cursor[k] ?? 0) + 1;
  }
  return { off, values };
}

interface GroupInput {
  readonly g: number;
  readonly from: number;
  readonly to: number;
  readonly n: number;
  readonly weightBytes: Uint8Array;
  readonly kindStateFile: Uint8Array;
  readonly canonFile: Uint8Array;
  readonly fwd: Int32Array;
  readonly fwdStart: Uint32Array;
  readonly recordSub: Uint32Array;
  readonly tokenCount: number;
  readonly subCount: number;
  /** File index to rank in its group; this group's entries are filled in. */
  readonly rankOf: Uint32Array;
}

function buildGroup(input: GroupInput): GroupData {
  const { g, kindStateFile, canonFile, recordSub } = input;
  const { from, to, rankOf } = input;
  const fileIndex = rankGroup(input.weightBytes, input.n, kindStateFile, g, from, to);
  const size = fileIndex.length;
  const kindState = new Uint8Array(size);
  const canon = new Uint8Array(size);
  for (let r = 0; r < size; r++) {
    const f = fileIndex[r] ?? 0;
    rankOf[f] = r;
    kindState[r] = kindStateFile[f] ?? 0;
    canon[r] = canonFile[f] ?? 0;
  }
  const { off, post } = buildPostings(
    from,
    to,
    rankOf,
    input.fwd,
    input.fwdStart,
    input.tokenCount,
  );
  // Places are searched for schools and districts only.
  let subOff: Uint32Array | null = null;
  let subRanks: Uint32Array | null = null;
  if (g === 0) {
    const subOfRank = new Uint32Array(size);
    for (let f = from; f < to; f++) subOfRank[rankOf[f] ?? 0] = recordSub[f] ?? 0;
    const bySub = invert(subOfRank, input.subCount);
    subOff = bySub.off;
    subRanks = bySub.values;
  }
  return {
    size,
    words: Math.ceil(size / 32),
    fileIndex,
    kindState,
    canon,
    nameOff: off,
    namePost: post,
    subOff,
    subRanks,
  };
}

/** Token to subs, for the place part of each sub. */
function buildPlaces(
  subs: readonly string[],
  subLoc: Uint32Array,
  tokenizer: IdTokenizer,
  tokenCount: number,
): { off: Uint32Array; subs: Uint32Array } {
  const owners: number[] = [];
  const begin = tokenizer.length;
  for (let s = 0; s < subs.length; s++) {
    const len = subLoc[s] ?? 0;
    if (len === 0) continue;
    const sub = subs[s] ?? '';
    if (len > sub.length) throw new IndexFormatError('place length out of range');
    const before = tokenizer.length;
    tokenizer.add(sub, 0, len);
    for (let k = before; k < tokenizer.length; k++) owners.push(s);
  }
  const tokens = new Uint32Array(tokenizer.data.buffer, begin * 4, tokenizer.length - begin);
  const { off, values } = invert(tokens, tokenCount);
  const out = new Uint32Array(values.length);
  for (let k = 0; k < values.length; k++) out[k] = owners[values[k] ?? 0] ?? 0;
  return { off, subs: out };
}

/**
 * Parses an uncompressed index and builds everything queries need.
 * `phases` receives milliseconds per step when given.
 */
export function loadIndex(bytes: Uint8Array, phases?: Record<string, number>): SearchIndex {
  let mark = performance.now();
  const lap = (name: string): void => {
    const now = performance.now();
    if (phases) phases[name] = (phases[name] ?? 0) + (now - mark);
    mark = now;
  };

  const header = readHeader(bytes);
  const { recordCount: n, subCount, tokenCount, groupCounts, sections } = header;
  const section = (s: number): Uint8Array => {
    const [a, b] = sections[s] ?? [0, 0];
    return bytes.subarray(a, b);
  };
  const decoder = new TextDecoder('utf-8', { fatal: true });

  const dict = readDictionary(section(Section.dictShared), section(Section.dictSuffix), tokenCount);
  const table = new TokenTable(dict);
  lap('dictionary');

  const names = decoder.decode(section(Section.names));
  const nameStart = lineStarts(names, n, 'names');
  const subsText = decoder.decode(section(Section.subs));
  const subStart = lineStarts(subsText, subCount, 'subs');
  const subs = new Array<string>(subCount);
  for (let s = 0; s < subCount; s++) {
    subs[s] = subsText.slice(subStart[s] ?? 0, (subStart[s + 1] ?? 1) - 1);
  }
  lap('text');

  const subLoc = readVarints(section(Section.subLoc), subCount, 'place');
  const recordSub = readRecordSubs(section(Section.recordSub), n, subCount);
  // Kept after loading, so copied: a view would keep the whole inflated
  // file alive.
  const kindStateFile = section(Section.kindState).slice();
  if (kindStateFile.length !== n) throw new IndexFormatError('kind section has the wrong size');
  const weightBytes = section(Section.weight);
  if (weightBytes.length !== n * 2) throw new IndexFormatError('weight section has the wrong size');
  const { lat, lon } = readCoords(section(Section.coords), n, recordSub, subCount);
  const ids = new IdColumn(section(Section.ids).slice(), header);
  lap('attributes');

  const tokenizer = new IdTokenizer(table, tokenCount);
  const { fwd, fwdStart, canon } = tokenizeNames(names, nameStart, n, tokenizer);
  lap('tokenize');

  const groups: GroupData[] = [];
  const rankOf = new Uint32Array(n);
  let from = 0;
  for (let g = 0; g < GROUP_COUNT; g++) {
    const to = from + (groupCounts[g] ?? 0);
    groups.push(
      buildGroup({
        g,
        from,
        to,
        n,
        weightBytes,
        kindStateFile,
        canonFile: canon,
        fwd,
        fwdStart,
        recordSub,
        tokenCount,
        subCount,
        rankOf,
      }),
    );
    from = to;
  }
  lap('postings');

  const places = buildPlaces(subs, subLoc, tokenizer, tokenCount);
  lap('places');

  const trie = new TokenTrie(dict);
  lap('trie');

  return new SearchIndex({
    recordCount: n,
    dict,
    trie,
    groups,
    locOff: places.off,
    locSubs: places.subs,
    names,
    nameStart,
    subs,
    recordSub,
    kindStateFile,
    lat,
    lon,
    coordScale: 10 ** header.coordDecimals,
    ids,
  });
}

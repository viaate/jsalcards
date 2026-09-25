/**
 * The search index file: layout constants and the byte-level readers and
 * writers both sides use.
 *
 * The file is gzip-compressed. Inside, all numbers are little-endian:
 *
 *   header (40 bytes)
 *     u32 magic 'SLSI'          u16 format version    u16 normalizer version
 *     u32 records               u32 unique subs       u32 dictionary tokens
 *     u32 × 3 records per group (schools, cities, zips), in that file order
 *     u8 coordinate decimals    u8 id flags (bit g: group g's ids equal names)
 *     u16 section count         u32 reserved
 *   section table: (u32 offset, u32 length) per section, in Section order
 *   sections:
 *     names       UTF-8, one name per record, each ended by '\n'
 *     subs        UTF-8, each unique sub once in code-unit order, ended by '\n'
 *     subLoc      varint per sub: UTF-16 length of the part that names a
 *                 place (the rest names the state); 0 when places of that sub
 *                 are not searched
 *     recordSub   varint per record: zigzag delta of its sub index
 *     kindState   u8 per record: kind << 6 | state index (see states.ts)
 *     weight      per record, quantizeWeight's 12 bits: all low bytes, then
 *                 all high bytes
 *     coords      lat and lon per record, scaled by 10^decimals, as zigzag
 *                 residuals from the last record with the same sub (or the
 *                 previous record when the sub is new): 3 byte planes, each
 *                 2 × records bytes, lowest first
 *     ids         per record of each group without its id flag, in order:
 *                 varint d > 0 when the id is the previous one plus d, both
 *                 all digits and of equal length; otherwise 0, then varint
 *                 shared prefix length (UTF-16), varint suffix byte length,
 *                 suffix UTF-8
 *     dictShared  u8 per dictionary token: prefix length shared with the
 *                 token before it
 *     dictSuffix  UTF-8, the rest of each token, each ended by '\n'
 *
 * The dictionary holds every token any name or place is indexed under,
 * sorted by UTF-16 code units. Records are stored grouped, and by id within a
 * group, which keeps ids, places and coordinates close to their neighbours so
 * they compress well. The worker orders them by weight when it loads.
 *
 * This module has no imports, so Node can load it directly from the builder.
 */

/** 'SLSI' read as a little-endian u32. */
export const MAGIC = 0x49534c53;
export const FORMAT_VERSION = 1;
export const HEADER_BYTES = 40;
/** 10^-4 degrees is about 11 m, finer than the sources' own geocoding. */
export const COORD_DECIMALS = 4;
/** Coordinate residuals are split into this many byte planes. */
export const COORD_PLANES = 3;

export const Section = {
  names: 0,
  subs: 1,
  subLoc: 2,
  recordSub: 3,
  kindState: 4,
  weight: 5,
  coords: 6,
  ids: 7,
  dictShared: 8,
  dictSuffix: 9,
} as const;
export const SECTION_COUNT = 10;

/** Kind codes as stored in kindState. */
export const KIND_CODES = ['school', 'district', 'city', 'zip'] as const;
/** Group of each kind code: districts rank with schools. */
export const GROUP_OF_KIND: readonly number[] = [0, 0, 1, 2];
export const GROUP_COUNT = 3;

/** Largest quantized weight. */
export const MAX_WEIGHT_CODE = 4095;

/**
 * Maps a weight onto 0..4095 on a log scale, in steps of about 0.5%, so
 * enrollments and populations keep their order to within half a percent.
 */
export function quantizeWeight(weight: number): number {
  if (!(weight > 0)) return 0;
  return Math.min(MAX_WEIGHT_CODE, Math.round(Math.log2(1 + weight) * 128));
}

export function zigzag(n: number): number {
  return ((n << 1) ^ (n >> 31)) >>> 0;
}

export function unzigzag(n: number): number {
  return (n >>> 1) ^ -(n & 1);
}

/** A growable byte buffer. */
export class ByteWriter {
  private buf = new Uint8Array(1 << 16);
  length = 0;

  private reserve(extra: number): void {
    if (this.length + extra <= this.buf.length) return;
    let size = this.buf.length * 2;
    while (size < this.length + extra) size *= 2;
    const next = new Uint8Array(size);
    next.set(this.buf.subarray(0, this.length));
    this.buf = next;
  }

  u8(value: number): void {
    this.reserve(1);
    this.buf[this.length++] = value & 0xff;
  }

  u16(value: number): void {
    this.reserve(2);
    this.buf[this.length++] = value & 0xff;
    this.buf[this.length++] = (value >>> 8) & 0xff;
  }

  u32(value: number): void {
    this.reserve(4);
    this.buf[this.length++] = value & 0xff;
    this.buf[this.length++] = (value >>> 8) & 0xff;
    this.buf[this.length++] = (value >>> 16) & 0xff;
    this.buf[this.length++] = (value >>> 24) & 0xff;
  }

  /** Unsigned LEB128, for values up to 2^32 - 1. */
  varint(value: number): void {
    if (!Number.isInteger(value) || value < 0 || value > 0xffffffff) {
      throw new RangeError(`varint out of range: ${String(value)}`);
    }
    this.reserve(5);
    let v = value;
    while (v >= 0x80) {
      this.buf[this.length++] = (v & 0x7f) | 0x80;
      v = Math.floor(v / 128);
    }
    this.buf[this.length++] = v;
  }

  bytes(data: Uint8Array): void {
    this.reserve(data.length);
    this.buf.set(data, this.length);
    this.length += data.length;
  }

  /** Overwrites a u32 written earlier. */
  patchU32(at: number, value: number): void {
    this.buf[at] = value & 0xff;
    this.buf[at + 1] = (value >>> 8) & 0xff;
    this.buf[at + 2] = (value >>> 16) & 0xff;
    this.buf[at + 3] = (value >>> 24) & 0xff;
  }

  finish(): Uint8Array {
    return this.buf.slice(0, this.length);
  }
}

/** Sequential reads over one section. Throws on reads past its end. */
export class ByteReader {
  readonly bytes: Uint8Array;
  readonly end: number;
  pos: number;

  constructor(bytes: Uint8Array, start = 0, end = bytes.length) {
    this.bytes = bytes;
    this.pos = start;
    this.end = end;
  }

  private need(n: number): void {
    if (this.pos + n > this.end) throw new RangeError('Snowlight search: index section ends early');
  }

  u8(): number {
    this.need(1);
    return this.bytes[this.pos++] ?? 0;
  }

  u16(): number {
    this.need(2);
    const b = this.bytes;
    const v = (b[this.pos] ?? 0) | ((b[this.pos + 1] ?? 0) << 8);
    this.pos += 2;
    return v;
  }

  u32(): number {
    this.need(4);
    const b = this.bytes;
    const p = this.pos;
    const v =
      ((b[p] ?? 0) | ((b[p + 1] ?? 0) << 8) | ((b[p + 2] ?? 0) << 16) | ((b[p + 3] ?? 0) << 24)) >>>
      0;
    this.pos += 4;
    return v;
  }

  varint(): number {
    const b = this.bytes;
    let result = 0;
    let scale = 1;
    for (let i = 0; i < 5; i++) {
      if (this.pos >= this.end) throw new RangeError('Snowlight search: index section ends early');
      const byte = b[this.pos++] ?? 0;
      result += (byte & 0x7f) * scale;
      if (byte < 0x80) return result;
      scale *= 128;
    }
    throw new RangeError('Snowlight search: malformed varint in index');
  }

  atEnd(): boolean {
    return this.pos === this.end;
  }
}

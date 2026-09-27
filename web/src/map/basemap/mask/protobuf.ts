/**
 * The little of Protocol Buffers that vector tiles need: reading fields one
 * by one, keeping any field's raw bytes to copy it unchanged, and writing
 * varints, packed varints and length-delimited fields.
 */

/** Wire types. */
export const VARINT = 0;
export const FIXED64 = 1;
export const BYTES = 2;
export const FIXED32 = 5;

/** One field read from a message. */
export interface Field {
  readonly tag: number;
  readonly type: number;
  /** Where the field starts (its key) and ends in the buffer: its raw bytes. */
  readonly start: number;
  readonly end: number;
  /** A varint's value; a length-delimited field's payload start. */
  readonly value: number;
  /** A length-delimited field's payload end. */
  readonly valueEnd: number;
}

export class Reader {
  readonly buf: Uint8Array;
  pos: number;
  readonly end: number;

  constructor(buf: Uint8Array, start = 0, end = buf.length) {
    this.buf = buf;
    this.pos = start;
    this.end = end;
  }

  /** A varint as a number: exact up to 2^53, which covers every value a tile carries that is read. */
  varint(): number {
    const buf = this.buf;
    let result = 0;
    let shift = 1;
    for (;;) {
      if (this.pos >= this.end) throw new Error('protobuf: truncated varint');
      const byte = buf[this.pos++] ?? 0;
      result += (byte & 0x7f) * shift;
      if (byte < 0x80) return result;
      shift *= 128;
      if (shift > 2 ** 63) throw new Error('protobuf: varint too long');
    }
  }

  /** The next field, or null at the end. Its payload is skipped. */
  next(): Field | null {
    if (this.pos >= this.end) return null;
    const start = this.pos;
    const key = this.varint();
    const tag = Math.floor(key / 8);
    const type = key % 8;
    let value = 0;
    let valueEnd = 0;
    switch (type) {
      case VARINT:
        value = this.varint();
        break;
      case FIXED64:
        this.pos += 8;
        break;
      case BYTES: {
        const length = this.varint();
        value = this.pos;
        valueEnd = this.pos + length;
        this.pos = valueEnd;
        break;
      }
      case FIXED32:
        this.pos += 4;
        break;
      default:
        throw new Error(`protobuf: unsupported wire type ${String(type)}`);
    }
    if (this.pos > this.end) throw new Error('protobuf: truncated field');
    return { tag, type, start, end: this.pos, value, valueEnd };
  }
}

/** A length-delimited field's payload as UTF-8 text. */
export function readString(buf: Uint8Array, field: Field): string {
  return new TextDecoder().decode(buf.subarray(field.value, field.valueEnd));
}

/** Packed varints in [start, end). */
export function readPacked(buf: Uint8Array, start: number, end: number): number[] {
  const reader = new Reader(buf, start, end);
  const values: number[] = [];
  while (reader.pos < end) values.push(reader.varint());
  return values;
}

const encoder = new TextEncoder();

/** A growable byte buffer that fields are appended to. */
export class Writer {
  private buf = new Uint8Array(256);
  length = 0;

  private reserve(bytes: number): void {
    if (this.length + bytes <= this.buf.length) return;
    let size = this.buf.length * 2;
    while (size < this.length + bytes) size *= 2;
    const grown = new Uint8Array(size);
    grown.set(this.buf.subarray(0, this.length));
    this.buf = grown;
  }

  varint(value: number): this {
    if (!Number.isInteger(value) || value < 0)
      throw new Error(`protobuf: bad varint ${String(value)}`);
    this.reserve(10);
    let rest = value;
    while (rest >= 0x80) {
      this.buf[this.length++] = (rest % 128) | 0x80;
      rest = Math.floor(rest / 128);
    }
    this.buf[this.length++] = rest;
    return this;
  }

  raw(bytes: Uint8Array): this {
    this.reserve(bytes.length);
    this.buf.set(bytes, this.length);
    this.length += bytes.length;
    return this;
  }

  key(tag: number, type: number): this {
    return this.varint(tag * 8 + type);
  }

  /** A varint field. */
  uint(tag: number, value: number): this {
    return this.key(tag, VARINT).varint(value);
  }

  /** A length-delimited field holding `bytes`. */
  bytes(tag: number, bytes: Uint8Array): this {
    return this.key(tag, BYTES).varint(bytes.length).raw(bytes);
  }

  string(tag: number, text: string): this {
    return this.bytes(tag, encoder.encode(text));
  }

  /** A packed repeated varint field. */
  packed(tag: number, values: readonly number[]): this {
    const inner = new Writer();
    for (const value of values) inner.varint(value);
    return this.bytes(tag, inner.finish());
  }

  finish(): Uint8Array {
    return this.buf.slice(0, this.length);
  }
}

/** Zigzag encoding of a signed integer, as vector tile geometry uses it. */
export function zigzag(value: number): number {
  return value >= 0 ? value * 2 : -value * 2 - 1;
}

export function unzigzag(value: number): number {
  return value % 2 === 0 ? value / 2 : -(value + 1) / 2;
}

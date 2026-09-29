/**
 * PMTiles version 3 (https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md),
 * written by the mask build script and read by the street tile workers.
 *
 * The reader asks for byte ranges: the header and root directory in one
 * request, then leaf directories and tiles as they are needed, directories
 * kept once read. The mask's directories are gzipped and its tiles stored as
 * they are (vector tiles of a few hundred bytes, many of them identical and
 * stored once, and kept once read). The school tiles
 * (pipeline/snowlight/directory/tiles.py) are gzipped too; the reader
 * unzips them, and keeps none of them: MapLibre keeps the tiles it shows.
 *
 * Where the ranges come from: the mask, under 1 MB, is fetched whole once
 * and read from memory (wholeFileReader); the school tiles, tens of MB, are
 * read over HTTP a range at a time (httpRangeReader), each range checked.
 * GitHub Pages' CDN gzips these files for a client that accepts it and then
 * applies a Range to the gzip, and a browser cache holding a whole gzip copy
 * answers ranges from it: a range read taken on trust can come back as
 * bytes of a compressed copy, for as long as the cached copy lives.
 */
import { backoffDelay, fetchBytes, sleep } from '../retry';
import type { Backoff, Fetch } from '../retry';
import { Reader, Writer } from './protobuf';

export const HEADER_BYTES = 127;
/** The header and root directory together fit in this many bytes, so one request reads both. */
export const ROOT_BYTES = 16_384;

const COMPRESSION_NONE = 1;
const COMPRESSION_GZIP = 2;
const TILE_TYPE_MVT = 1;

export interface Entry {
  readonly tileId: number;
  readonly offset: number;
  readonly length: number;
  /** Tiles in a row sharing these bytes; 0 marks a leaf directory. */
  readonly runLength: number;
}

export interface Header {
  readonly rootOffset: number;
  readonly rootLength: number;
  readonly metadataOffset: number;
  readonly metadataLength: number;
  readonly leafOffset: number;
  readonly leafLength: number;
  readonly tileDataOffset: number;
  readonly tileDataLength: number;
  readonly addressedTiles: number;
  readonly tileEntries: number;
  readonly tileContents: number;
  readonly clustered: boolean;
  readonly internalCompression: number;
  readonly tileCompression: number;
  readonly tileType: number;
  readonly minZoom: number;
  readonly maxZoom: number;
  /** West, south, east, north in degrees. */
  readonly bounds: readonly [number, number, number, number];
  readonly center: readonly [lon: number, lat: number, zoom: number];
}

/** Tiles above zoom z, all counted: where zoom z's ids start. */
function zoomStart(z: number): number {
  return (4 ** z - 1) / 3;
}

/** A tile's id: its zoom's start plus its place along a Hilbert curve over the zoom. */
export function zxyToTileId(z: number, x: number, y: number): number {
  const n = 2 ** z;
  if (!Number.isInteger(z) || z < 0 || z > 26 || x < 0 || y < 0 || x >= n || y >= n) {
    throw new Error(`pmtiles: no tile ${String(z)}/${String(x)}/${String(y)}`);
  }
  let d = 0;
  let tx = x;
  let ty = y;
  for (let s = n / 2; s >= 1; s /= 2) {
    const rx = Math.floor(tx / s) % 2;
    const ry = Math.floor(ty / s) % 2;
    d += s * s * ((3 * rx) ^ ry);
    if (ry === 0) {
      if (rx === 1) {
        tx = s - 1 - (tx % s);
        ty = s - 1 - (ty % s);
      }
      [tx, ty] = [ty, tx];
    }
    tx %= s;
    ty %= s;
  }
  return zoomStart(z) + d;
}

export function serializeDirectory(entries: readonly Entry[]): Uint8Array {
  const writer = new Writer();
  writer.varint(entries.length);
  let lastId = 0;
  for (const entry of entries) {
    writer.varint(entry.tileId - lastId);
    lastId = entry.tileId;
  }
  for (const entry of entries) writer.varint(entry.runLength);
  for (const entry of entries) writer.varint(entry.length);
  entries.forEach((entry, i) => {
    const previous = i > 0 ? entries[i - 1] : undefined;
    if (previous !== undefined && entry.offset === previous.offset + previous.length) {
      writer.varint(0);
    } else {
      writer.varint(entry.offset + 1);
    }
  });
  return writer.finish();
}

export function deserializeDirectory(bytes: Uint8Array): Entry[] {
  const reader = new Reader(bytes);
  const count = reader.varint();
  const ids: number[] = [];
  let lastId = 0;
  for (let i = 0; i < count; i++) {
    lastId += reader.varint();
    ids.push(lastId);
  }
  const runs = Array.from({ length: count }, () => reader.varint());
  const lengths = Array.from({ length: count }, () => reader.varint());
  const entries: Entry[] = [];
  for (let i = 0; i < count; i++) {
    const raw = reader.varint();
    const previous = entries[i - 1];
    const length = lengths[i] ?? 0;
    const offset =
      raw === 0 && previous !== undefined ? previous.offset + previous.length : raw - 1;
    entries.push({ tileId: ids[i] ?? 0, offset, length, runLength: runs[i] ?? 0 });
  }
  return entries;
}

/** The entry that holds `tileId`, a leaf directory that may, or null. */
export function findEntry(entries: readonly Entry[], tileId: number): Entry | null {
  let low = 0;
  let high = entries.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const entry = entries[mid];
    if (entry === undefined) break;
    if (entry.tileId < tileId) low = mid + 1;
    else if (entry.tileId > tileId) high = mid - 1;
    else return entry;
  }
  const entry = entries[high];
  if (entry === undefined) return null;
  if (entry.runLength === 0 || tileId - entry.tileId < entry.runLength) return entry;
  return null;
}

function writeU64(view: DataView, at: number, value: number): void {
  view.setBigUint64(at, BigInt(value), true);
}

function readU64(view: DataView, at: number): number {
  return Number(view.getBigUint64(at, true));
}

export function encodeHeader(header: Header): Uint8Array {
  const bytes = new Uint8Array(HEADER_BYTES);
  bytes.set(new TextEncoder().encode('PMTiles'), 0);
  bytes[7] = 3;
  const view = new DataView(bytes.buffer);
  const u64 = [
    header.rootOffset,
    header.rootLength,
    header.metadataOffset,
    header.metadataLength,
    header.leafOffset,
    header.leafLength,
    header.tileDataOffset,
    header.tileDataLength,
    header.addressedTiles,
    header.tileEntries,
    header.tileContents,
  ];
  u64.forEach((value, i) => {
    writeU64(view, 8 + i * 8, value);
  });
  view.setUint8(96, header.clustered ? 1 : 0);
  view.setUint8(97, header.internalCompression);
  view.setUint8(98, header.tileCompression);
  view.setUint8(99, header.tileType);
  view.setUint8(100, header.minZoom);
  view.setUint8(101, header.maxZoom);
  const e7 = (degrees: number): number => Math.round(degrees * 1e7);
  const [west, south, east, north] = header.bounds;
  view.setInt32(102, e7(west), true);
  view.setInt32(106, e7(south), true);
  view.setInt32(110, e7(east), true);
  view.setInt32(114, e7(north), true);
  view.setUint8(118, header.center[2]);
  view.setInt32(119, e7(header.center[0]), true);
  view.setInt32(123, e7(header.center[1]), true);
  return bytes;
}

export function decodeHeader(bytes: Uint8Array): Header {
  if (bytes.length < HEADER_BYTES || new TextDecoder().decode(bytes.subarray(0, 7)) !== 'PMTiles') {
    throw new Error('pmtiles: not a PMTiles archive');
  }
  if (bytes[7] !== 3) throw new Error(`pmtiles: version ${String(bytes[7])}, expected 3`);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const u64 = (i: number): number => readU64(view, 8 + i * 8);
  const e7 = (at: number): number => view.getInt32(at, true) / 1e7;
  return {
    rootOffset: u64(0),
    rootLength: u64(1),
    metadataOffset: u64(2),
    metadataLength: u64(3),
    leafOffset: u64(4),
    leafLength: u64(5),
    tileDataOffset: u64(6),
    tileDataLength: u64(7),
    addressedTiles: u64(8),
    tileEntries: u64(9),
    tileContents: u64(10),
    clustered: view.getUint8(96) === 1,
    internalCompression: view.getUint8(97),
    tileCompression: view.getUint8(98),
    tileType: view.getUint8(99),
    minZoom: view.getUint8(100),
    maxZoom: view.getUint8(101),
    bounds: [e7(102), e7(106), e7(110), e7(114)],
    center: [e7(119), e7(123), view.getUint8(118)],
  };
}

export interface ArchiveTile {
  readonly z: number;
  readonly x: number;
  readonly y: number;
  readonly bytes: Uint8Array;
}

export interface ArchiveOptions {
  readonly metadata: unknown;
  readonly bounds: readonly [number, number, number, number];
  readonly center: readonly [lon: number, lat: number, zoom: number];
  /** gzip, from the platform: node:zlib in the build. */
  readonly gzip: (bytes: Uint8Array) => Uint8Array;
}

function concat(parts: readonly Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

function key(bytes: Uint8Array): string {
  // Tiles are small; their bytes as text make an exact key for finding repeats.
  let text = '';
  for (const byte of bytes) text += String.fromCharCode(byte);
  return text;
}

/**
 * A complete archive: tiles in id order, each distinct content stored once,
 * runs of a repeated tile in one entry, and the directory split into leaves
 * when it would not fit in the first ROOT_BYTES.
 */
export function writeArchive(tiles: readonly ArchiveTile[], options: ArchiveOptions): Uint8Array {
  const sorted = tiles
    .map((tile) => ({ id: zxyToTileId(tile.z, tile.x, tile.y), tile }))
    .sort((a, b) => a.id - b.id);
  const data: Uint8Array[] = [];
  let dataLength = 0;
  const stored = new Map<string, { offset: number; length: number }>();
  const entries: Entry[] = [];
  for (const { id, tile } of sorted) {
    const previous = entries[entries.length - 1];
    if (previous?.tileId === id) {
      throw new Error(`pmtiles: tile ${String(tile.z)}/${String(tile.x)}/${String(tile.y)} twice`);
    }
    const content = key(tile.bytes);
    let place = stored.get(content);
    if (place === undefined) {
      place = { offset: dataLength, length: tile.bytes.length };
      stored.set(content, place);
      data.push(tile.bytes);
      dataLength += tile.bytes.length;
    }
    if (previous?.offset === place.offset && previous.tileId + previous.runLength === id) {
      entries[entries.length - 1] = { ...previous, runLength: previous.runLength + 1 };
    } else {
      entries.push({ tileId: id, offset: place.offset, length: place.length, runLength: 1 });
    }
  }

  const metadata = options.gzip(new TextEncoder().encode(JSON.stringify(options.metadata)));
  let root = options.gzip(serializeDirectory(entries));
  let leaves: Uint8Array = new Uint8Array(0);
  // Split into leaves, larger each try, until the root fits beside the header.
  for (let leafSize = 4096; HEADER_BYTES + root.length > ROOT_BYTES; leafSize *= 2) {
    const leafParts: Uint8Array[] = [];
    const rootEntries: Entry[] = [];
    let leafOffset = 0;
    for (let i = 0; i < entries.length; i += leafSize) {
      const chunk = entries.slice(i, i + leafSize);
      const leaf = options.gzip(serializeDirectory(chunk));
      rootEntries.push({
        tileId: chunk[0]?.tileId ?? 0,
        offset: leafOffset,
        length: leaf.length,
        runLength: 0,
      });
      leafParts.push(leaf);
      leafOffset += leaf.length;
    }
    root = options.gzip(serializeDirectory(rootEntries));
    leaves = concat(leafParts);
  }

  const zooms = tiles.map((tile) => tile.z);
  const rootOffset = HEADER_BYTES;
  const metadataOffset = rootOffset + root.length;
  const leafOffset = metadataOffset + metadata.length;
  const tileDataOffset = leafOffset + leaves.length;
  const header = encodeHeader({
    rootOffset,
    rootLength: root.length,
    metadataOffset,
    metadataLength: metadata.length,
    leafOffset,
    leafLength: leaves.length,
    tileDataOffset,
    tileDataLength: dataLength,
    addressedTiles: sorted.length,
    tileEntries: entries.length,
    tileContents: data.length,
    clustered: true,
    internalCompression: COMPRESSION_GZIP,
    tileCompression: COMPRESSION_NONE,
    tileType: TILE_TYPE_MVT,
    minZoom: zooms.length > 0 ? Math.min(...zooms) : 0,
    maxZoom: zooms.length > 0 ? Math.max(...zooms) : 0,
    bounds: options.bounds,
    center: options.center,
  });
  return concat([header, root, metadata, leaves, ...data]);
}

/** Reads `length` bytes at `offset` of the archive. */
export type RangeReader = (offset: number, length: number) => Promise<Uint8Array>;

/** Gunzips bytes: DecompressionStream in the browser, node:zlib in tests. */
export type Gunzip = (bytes: Uint8Array) => Promise<Uint8Array>;

export async function gunzipWithStreams(bytes: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([bytes as Uint8Array<ArrayBuffer>])
    .stream()
    .pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export interface ArchiveReaderOptions {
  /** Keep each tile once read, for the next request of it. Default true. */
  readonly keepTiles?: boolean;
}

/** An archive read through byte ranges, directories (and, unless told not to, tiles) kept once read. */
export class ArchiveReader {
  private readonly read: RangeReader;
  private readonly gunzip: Gunzip;
  private readonly keepTiles: boolean;
  private header: Promise<{ header: Header; root: Entry[] }> | undefined;
  private readonly leaves = new Map<number, Promise<Entry[]>>();
  private readonly tiles = new Map<number, Promise<Uint8Array>>();

  constructor(
    read: RangeReader,
    gunzip: Gunzip = gunzipWithStreams,
    options: ArchiveReaderOptions = {},
  ) {
    this.read = read;
    this.gunzip = gunzip;
    this.keepTiles = options.keepTiles ?? true;
  }

  private async directory(bytes: Uint8Array, compression: number): Promise<Entry[]> {
    if (compression === COMPRESSION_GZIP) return deserializeDirectory(await this.gunzip(bytes));
    if (compression === COMPRESSION_NONE) return deserializeDirectory(bytes);
    throw new Error(`pmtiles: unsupported compression ${String(compression)}`);
  }

  /** The header and root directory; a failed read is tried again next time. */
  start(): Promise<{ header: Header; root: Entry[] }> {
    this.header ??= (async () => {
      const first = await this.read(0, ROOT_BYTES);
      const header = decodeHeader(first);
      if (header.tileType !== TILE_TYPE_MVT) throw new Error('pmtiles: not vector tiles');
      if (
        header.tileCompression !== COMPRESSION_NONE &&
        header.tileCompression !== COMPRESSION_GZIP
      ) {
        throw new Error(`pmtiles: unsupported tile compression ${String(header.tileCompression)}`);
      }
      const end = header.rootOffset + header.rootLength;
      const rootBytes =
        end <= first.length
          ? first.subarray(header.rootOffset, end)
          : await this.read(header.rootOffset, header.rootLength);
      return {
        header,
        root: await this.directory(rootBytes, header.internalCompression),
      };
    })().catch((error: unknown) => {
      this.header = undefined;
      throw error;
    });
    return this.header;
  }

  private leaf(header: Header, entry: Entry): Promise<Entry[]> {
    const at = header.leafOffset + entry.offset;
    let leaf = this.leaves.get(at);
    if (leaf === undefined) {
      leaf = this.read(at, entry.length).then((bytes) =>
        this.directory(bytes, header.internalCompression),
      );
      leaf.catch(() => this.leaves.delete(at));
      this.leaves.set(at, leaf);
    }
    return leaf;
  }

  /** Where a tile's bytes are, or null when the archive has no such tile. */
  async locate(z: number, x: number, y: number): Promise<Entry | null> {
    const { header, root } = await this.start();
    if (z < header.minZoom || z > header.maxZoom) return null;
    const id = zxyToTileId(z, x, y);
    let entries = root;
    for (let depth = 0; depth < 4; depth++) {
      const entry = findEntry(entries, id);
      if (entry === null) return null;
      if (entry.runLength > 0) return entry;
      entries = await this.leaf(header, entry);
    }
    throw new Error('pmtiles: directories nested too deep');
  }

  /**
   * A tile's bytes, unzipped, or null. Kept tiles stored once are read once,
   * whichever ids they serve.
   */
  async tile(z: number, x: number, y: number): Promise<Uint8Array | null> {
    const entry = await this.locate(z, x, y);
    if (entry === null) return null;
    const { header } = await this.start();
    const at = header.tileDataOffset + entry.offset;
    let bytes = this.tiles.get(at);
    if (bytes === undefined) {
      const read = this.read(at, entry.length);
      bytes =
        header.tileCompression === COMPRESSION_GZIP
          ? read.then((zipped) => this.gunzip(zipped))
          : read;
      if (this.keepTiles) {
        bytes.catch(() => this.tiles.delete(at));
        this.tiles.set(at, bytes);
      }
    }
    return bytes;
  }
}

/** How a reader over HTTP fetches, waits and unzips: the platform's own, or a test's. */
export interface HttpReaderOptions {
  readonly fetch?: Fetch;
  readonly sleep?: (ms: number) => Promise<void>;
  readonly random?: () => number;
  readonly gunzip?: Gunzip;
}

const platformFetch: Fetch = (url, init) => fetch(url, init);

/**
 * How long a read over HTTP may go with none of its answer arriving, in
 * milliseconds, before it is given up on and made again: a request a network
 * holds without an answer would otherwise hold its tile, or every street
 * tile, for good. An answer that keeps coming, however slowly, is waited for.
 */
export const READ_STALL_MS = 12_000;

/** Tries at a byte range before the read fails, and its tile (the page asks for that again). */
export const RANGE_TRIES = 3;
/** Waits between them, in milliseconds. */
export const RANGE_BACKOFF: Backoff = [300, 1200];

/** The parts of a Content-Range header: `bytes first-last/size`, the size perhaps unknown. */
function contentRange(value: string | null): { first: number; last: number; size: number | null } {
  const match = /^\s*bytes\s+(\d+)-(\d+)\/(\d+|\*)\s*$/i.exec(value ?? '');
  if (match === null) return { first: -1, last: -1, size: null };
  const [, first = '', last = '', size = '*'] = match;
  return { first: Number(first), last: Number(last), size: size === '*' ? null : Number(size) };
}

/**
 * One read of `length` bytes at `offset`, checked: a 206 must hold exactly
 * those bytes of the file as it is (not of a compressed copy of it: a server
 * may apply a range to the gzip it sends, and a cache may answer a range from
 * a whole copy it holds compressed), or a 200 the whole file, cut here.
 */
async function readRangeOnce(
  url: string,
  offset: number,
  length: number,
  get: Fetch,
): Promise<Uint8Array> {
  const last = offset + length - 1;
  const { response, bytes } = await fetchBytes(
    url,
    READ_STALL_MS,
    undefined,
    {
      headers: { Range: `bytes=${String(offset)}-${String(last)}` },
      // Past the browser's cache both ways: whatever it holds of this file cannot answer a range.
      cache: 'no-store',
    },
    get,
  );
  if (!response.ok) throw new Error(`${url}: HTTP ${String(response.status)}`);
  if (response.status === 206) {
    const encoding = response.headers.get('content-encoding');
    if (encoding !== null && encoding.trim().toLowerCase() !== 'identity') {
      throw new Error(`${url}: bytes ${String(offset)}-${String(last)} of its ${encoding} copy`);
    }
    const range = contentRange(response.headers.get('content-range'));
    const whole = range.size !== null && range.last === range.size - 1;
    if (
      range.first !== offset ||
      range.last > last ||
      bytes.length !== range.last - range.first + 1 ||
      (range.last < last && !whole)
    ) {
      const got = `${String(bytes.length)} as "${response.headers.get('content-range') ?? ''}"`;
      throw new Error(`${url}: asked for bytes ${String(offset)}-${String(last)}, got ${got}`);
    }
    return bytes;
  }
  // A server that ignores Range sends the whole file (the browser unzips it, if it came zipped).
  if (bytes.length <= offset) {
    throw new Error(
      `${url}: ${String(bytes.length)} bytes, asked for bytes from ${String(offset)}`,
    );
  }
  return bytes.slice(offset, offset + length);
}

/**
 * Reads byte ranges of a file over HTTP, taking a whole-file answer too.
 * Each read goes past the browser's cache, is checked (readRangeOnce), and is
 * tried RANGE_TRIES times before it fails.
 */
export function httpRangeReader(url: string, options: HttpReaderOptions = {}): RangeReader {
  const get = options.fetch ?? platformFetch;
  const wait = options.sleep ?? ((ms: number) => sleep(ms));
  return async (offset, length) => {
    let failure: unknown;
    for (let attempt = 0; attempt < RANGE_TRIES; attempt++) {
      if (attempt > 0) await wait(backoffDelay(RANGE_BACKOFF, attempt - 1, options.random));
      try {
        return await readRangeOnce(url, offset, length, get);
      } catch (error) {
        failure = error;
      }
    }
    throw failure;
  };
}

/**
 * Waits between tries at a whole file, in milliseconds: it is tried until it
 * comes, never more than about ten seconds apart, and at once when woken
 * (WholeFileOptions `sleep`).
 */
export const WHOLE_FILE_BACKOFF: Backoff = [500, 1000, 2000, 4000, 8000, 10_000];

/**
 * Checks that `bytes` is a whole PMTiles archive: its header, and every byte
 * the header says it has. A cut-short copy, or the gzip of one, is not.
 */
export function checkWholeArchive(bytes: Uint8Array): void {
  const header = decodeHeader(bytes);
  const end = Math.max(
    header.rootOffset + header.rootLength,
    header.metadataOffset + header.metadataLength,
    header.leafOffset + header.leafLength,
    header.tileDataOffset + header.tileDataLength,
  );
  if (bytes.length < end) {
    throw new Error(`pmtiles: ${String(bytes.length)} bytes of ${String(end)}`);
  }
}

/** Whether bytes start as a gzip stream does. */
const isGzip = (bytes: Uint8Array): boolean => bytes[0] === 0x1f && bytes[1] === 0x8b;

/** How a whole file is asked for, besides how a reader over HTTP fetches, waits and unzips. */
export interface WholeFileOptions extends HttpReaderOptions {
  /**
   * Where to ask instead once the file's own URL answers 404: a copy under a
   * name that does not change (a page from an older build asks for a file
   * the site no longer has).
   */
  readonly fallbackUrl?: string;
}

/**
 * A small archive, fetched whole: asked for without a Range, so no server or
 * cache can answer with part of a compressed copy (the browser unzips a
 * whole one; a gzip handed over still zipped is unzipped here), and checked
 * (checkWholeArchive) before it is taken. Anything else, or a request that
 * stalls (READ_STALL_MS), is asked for again, past the browser's cache, with
 * growing waits (WHOLE_FILE_BACKOFF), until the whole file comes: the promise
 * never rejects.
 */
export async function loadWholeArchive(
  url: string,
  options: WholeFileOptions = {},
): Promise<Uint8Array> {
  const get = options.fetch ?? platformFetch;
  const wait = options.sleep ?? ((ms: number) => sleep(ms));
  const gunzip = options.gunzip ?? gunzipWithStreams;
  let from = url;
  for (let attempt = 0; ; attempt++) {
    if (attempt > 0) await wait(backoffDelay(WHOLE_FILE_BACKOFF, attempt - 1, options.random));
    try {
      // After a wrong answer, from the server: the cache may hold part of the file, or its gzip.
      const init: RequestInit = attempt === 0 ? {} : { cache: 'reload' };
      const answer = await fetchBytes(from, READ_STALL_MS, undefined, init, get);
      if (answer.response.status === 404 && options.fallbackUrl !== undefined) {
        from = options.fallbackUrl;
      }
      if (!answer.response.ok) throw new Error(`${from}: HTTP ${String(answer.response.status)}`);
      const bytes = isGzip(answer.bytes) ? await gunzip(answer.bytes) : answer.bytes;
      checkWholeArchive(bytes);
      return bytes;
    } catch (error) {
      if (attempt === 0) console.warn(`Snowlight: ${url} came back wrong; asking again`, error);
    }
  }
}

/** A reader of byte ranges of bytes already in memory, or on their way. */
export function memoryReader(url: string, file: () => Promise<Uint8Array>): RangeReader {
  return async (offset, length) => {
    const bytes = await file();
    if (offset >= bytes.length) {
      throw new Error(`${url}: no bytes at ${String(offset)} of ${String(bytes.length)}`);
    }
    return bytes.subarray(offset, offset + length);
  };
}

/**
 * Reads byte ranges of a small archive fetched whole, once, and kept
 * (loadWholeArchive): the US mask, in a worker that is not handed it by the
 * page (street-tiles.ts). Nothing is asked of the network until the first
 * read; reads wait for the file meanwhile.
 */
export function wholeFileReader(url: string, options: WholeFileOptions = {}): RangeReader {
  let file: Promise<Uint8Array> | undefined;
  return memoryReader(url, () => {
    file ??= loadWholeArchive(url, options);
    return file;
  });
}

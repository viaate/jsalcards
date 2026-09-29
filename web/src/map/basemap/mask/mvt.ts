/**
 * Mapbox Vector Tiles (the format OpenFreeMap serves and the US mask is stored
 * in), read and written at the level the mask needs: layers and features are
 * kept as raw bytes, so a feature that passes through unchanged is copied
 * byte for byte, and only the geometry of a feature that changes is decoded
 * and written anew. Properties are never decoded.
 *
 * Geometry is handled as parts: flat [x0, y0, x1, y1, ...] arrays in tile
 * units. A point feature has one part per point, a line one per line string,
 * a polygon one per ring (not repeating its first point).
 */
import { BYTES, Reader, Writer, readPacked, readString, unzigzag, zigzag } from './protobuf';

export const POINT = 1;
export const LINE = 2;
export const POLYGON = 3;

/** Tile units across a tile, as OpenMapTiles and the mask use. */
export const EXTENT = 4096;

/** Layer message fields. */
const LAYER_NAME = 1;
const LAYER_FEATURES = 2;
const LAYER_KEYS = 3;
const LAYER_VALUES = 4;
const LAYER_EXTENT = 5;
const LAYER_VERSION = 15;
/** Feature message fields. */
const FEATURE_TAGS = 2;
const FEATURE_TYPE = 3;
const FEATURE_GEOMETRY = 4;
/** Tile message field. */
const TILE_LAYERS = 3;

const MOVE_TO = 1;
const LINE_TO = 2;
const CLOSE_PATH = 7;

export type Parts = number[][];

export class Feature {
  /** The feature message. */
  readonly raw: Uint8Array;
  readonly type: number;
  /** Where the packed geometry sits in `raw`, and the raw bytes of every other field. */
  private readonly geometryStart: number;
  private readonly geometryEnd: number;
  private readonly others: readonly Uint8Array[];
  /** Where the packed tags sit in `raw`. */
  private readonly tagsStart: number;
  private readonly tagsEnd: number;
  private decoded: Parts | undefined;

  constructor(
    raw: Uint8Array,
    type: number,
    geometry: readonly [start: number, end: number],
    tags: readonly [start: number, end: number],
    others: readonly Uint8Array[],
  ) {
    this.raw = raw;
    this.type = type;
    [this.geometryStart, this.geometryEnd] = geometry;
    [this.tagsStart, this.tagsEnd] = tags;
    this.others = others;
  }

  /** Key and value indices, alternating. */
  tags(): number[] {
    return readPacked(this.raw, this.tagsStart, this.tagsEnd);
  }

  /** The geometry, decoded once. */
  parts(): Parts {
    this.decoded ??= decodeGeometry(readPacked(this.raw, this.geometryStart, this.geometryEnd));
    return this.decoded;
  }

  /** The feature message with the same id, type and geometry, and these tags. */
  withTags(tags: readonly number[]): Uint8Array {
    const writer = new Writer();
    let written = false;
    const reader = new Reader(this.raw);
    for (let field = reader.next(); field !== null; field = reader.next()) {
      if (field.tag === FEATURE_TAGS && field.type === BYTES) {
        if (!written) writer.packed(FEATURE_TAGS, tags);
        written = true;
      } else writer.raw(this.raw.subarray(field.start, field.end));
    }
    if (!written) writer.packed(FEATURE_TAGS, tags);
    return writer.finish();
  }

  /**
   * The feature message with the same id, properties and type, and this
   * geometry; null when none of it is left to write (encodeGeometry).
   */
  withParts(parts: Parts): Uint8Array | null {
    const geometry = encodeGeometry(this.type, parts);
    if (geometry.length === 0) return null;
    const writer = new Writer();
    for (const field of this.others) writer.raw(field);
    writer.packed(FEATURE_GEOMETRY, geometry);
    return writer.finish();
  }
}

export interface Layer {
  readonly name: string;
  readonly extent: number;
  /** Raw bytes of every field but the features: name, keys, values, extent, version. */
  readonly fields: readonly Uint8Array[];
  readonly features: Feature[];
  /** Property keys, and string values (other values as null), by index. */
  readonly keys: readonly string[];
  readonly values: readonly (string | null)[];
}

function parseFeature(buf: Uint8Array): Feature {
  const reader = new Reader(buf);
  const others: Uint8Array[] = [];
  let type = 0;
  let geometryStart = 0;
  let geometryEnd = 0;
  let tagsStart = 0;
  let tagsEnd = 0;
  for (let field = reader.next(); field !== null; field = reader.next()) {
    if (field.tag === FEATURE_GEOMETRY && field.type === BYTES) {
      geometryStart = field.value;
      geometryEnd = field.valueEnd;
      continue;
    }
    if (field.tag === FEATURE_TYPE) type = field.value;
    if (field.tag === FEATURE_TAGS && field.type === BYTES) {
      tagsStart = field.value;
      tagsEnd = field.valueEnd;
    }
    others.push(buf.subarray(field.start, field.end));
  }
  return new Feature(buf, type, [geometryStart, geometryEnd], [tagsStart, tagsEnd], others);
}

/** A Value message's string, or null for any other kind of value. */
function stringValue(buf: Uint8Array, start: number, end: number): string | null {
  const reader = new Reader(buf, start, end);
  for (let field = reader.next(); field !== null; field = reader.next()) {
    if (field.tag === 1 && field.type === BYTES) return readString(buf, field);
  }
  return null;
}

function parseLayer(buf: Uint8Array): Layer {
  const reader = new Reader(buf);
  const fields: Uint8Array[] = [];
  const features: Feature[] = [];
  const keys: string[] = [];
  const values: (string | null)[] = [];
  let name = '';
  let extent = EXTENT;
  for (let field = reader.next(); field !== null; field = reader.next()) {
    if (field.tag === LAYER_FEATURES && field.type === BYTES) {
      features.push(parseFeature(buf.subarray(field.value, field.valueEnd)));
      continue;
    }
    if (field.tag === LAYER_NAME && field.type === BYTES) name = readString(buf, field);
    if (field.tag === LAYER_EXTENT) extent = field.value;
    if (field.tag === LAYER_KEYS && field.type === BYTES) keys.push(readString(buf, field));
    if (field.tag === LAYER_VALUES && field.type === BYTES) {
      values.push(stringValue(buf, field.value, field.valueEnd));
    }
    fields.push(buf.subarray(field.start, field.end));
  }
  return { name, extent, fields, features, keys, values };
}

/** A feature's string property, or null when it has none by that name. */
export function stringProperty(layer: Layer, feature: Feature, name: string): string | null {
  const key = layer.keys.indexOf(name);
  if (key < 0) return null;
  const tags = feature.tags();
  for (let i = 0; i + 1 < tags.length; i += 2) {
    if (tags[i] === key) return layer.values[tags[i + 1] ?? -1] ?? null;
  }
  return null;
}

/** The layers of a tile. Their bytes are views into `bytes`. */
export function decodeTile(bytes: Uint8Array): Layer[] {
  const reader = new Reader(bytes);
  const layers: Layer[] = [];
  for (let field = reader.next(); field !== null; field = reader.next()) {
    if (field.tag === TILE_LAYERS && field.type === BYTES) {
      layers.push(parseLayer(bytes.subarray(field.value, field.valueEnd)));
    }
  }
  return layers;
}

/** A layer to write: its non-feature fields and its feature messages, raw. */
export interface LayerOutput {
  readonly fields: readonly Uint8Array[];
  readonly features: readonly Uint8Array[];
}

/** A tile from its layers. */
export function encodeTile(layers: readonly LayerOutput[]): Uint8Array {
  const tile = new Writer();
  for (const layer of layers) {
    const writer = new Writer();
    for (const field of layer.fields) writer.raw(field);
    for (const feature of layer.features) writer.bytes(LAYER_FEATURES, feature);
    tile.bytes(TILE_LAYERS, writer.finish());
  }
  return tile.finish();
}

/** A new layer with no properties: each feature is a geometry type and its parts. */
export function newLayer(
  name: string,
  features: readonly { readonly type: number; readonly parts: Parts }[],
  extent = EXTENT,
): LayerOutput {
  const fields = [
    new Writer().string(LAYER_NAME, name).finish(),
    new Writer().uint(LAYER_EXTENT, extent).finish(),
    new Writer().uint(LAYER_VERSION, 2).finish(),
  ];
  return {
    fields,
    // Only features with some geometry left to write (encodeGeometry).
    features: features.flatMap((feature) => {
      const geometry = encodeGeometry(feature.type, feature.parts);
      if (geometry.length === 0) return [];
      return [
        new Writer().uint(FEATURE_TYPE, feature.type).packed(FEATURE_GEOMETRY, geometry).finish(),
      ];
    }),
  };
}

function command(id: number, count: number): number {
  return (count << 3) | id;
}

/** Parts of a geometry: a point feature's MoveTo of n points gives n parts. */
export function decodeGeometry(ints: readonly number[]): Parts {
  const parts: Parts = [];
  let x = 0;
  let y = 0;
  let current: number[] | undefined;
  let i = 0;
  while (i < ints.length) {
    const header = ints[i++] ?? 0;
    const id = header & 7;
    const count = header >> 3;
    if (id === MOVE_TO || id === LINE_TO) {
      for (let k = 0; k < count; k++) {
        x += unzigzag(ints[i++] ?? 0);
        y += unzigzag(ints[i++] ?? 0);
        if (id === MOVE_TO) {
          current = [x, y];
          parts.push(current);
        } else {
          current?.push(x, y);
        }
      }
    } else if (id !== CLOSE_PATH) {
      throw new Error(`mvt: unknown command ${String(id)}`);
    }
  }
  return parts;
}

/**
 * Geometry commands for parts. Repeated points are dropped; a line needs two
 * points and a ring three, or the part is left out. Parts cut out of a line or
 * a ring and rounded to whole tile units can come down to a single point
 * (a road's last few centimetres past the border): with every part left out,
 * there are no commands at all, and a feature with none must not be written
 * (Feature.withParts, newLayer): MapLibre's worker fails the whole tile on
 * it, and the tile is never drawn.
 */
export function encodeGeometry(type: number, parts: Parts): number[] {
  const out: number[] = [];
  let x = 0;
  let y = 0;
  if (type === POINT) {
    const points = parts.filter((part) => part.length >= 2);
    if (points.length === 0) return out;
    out.push(command(MOVE_TO, points.length));
    for (const part of points) {
      const px = part[0] ?? 0;
      const py = part[1] ?? 0;
      out.push(zigzag(px - x), zigzag(py - y));
      x = px;
      y = py;
    }
    return out;
  }
  const minimum = type === POLYGON ? 3 : 2;
  for (const part of parts) {
    const points = dedupe(part, type === POLYGON);
    if (points.length / 2 < minimum) continue;
    out.push(command(MOVE_TO, 1));
    out.push(zigzag((points[0] ?? 0) - x), zigzag((points[1] ?? 0) - y));
    x = points[0] ?? 0;
    y = points[1] ?? 0;
    out.push(command(LINE_TO, points.length / 2 - 1));
    for (let i = 2; i < points.length; i += 2) {
      const px = points[i] ?? 0;
      const py = points[i + 1] ?? 0;
      out.push(zigzag(px - x), zigzag(py - y));
      x = px;
      y = py;
    }
    if (type === POLYGON) out.push(command(CLOSE_PATH, 1));
  }
  return out;
}

/** The part without consecutive repeated points (nor, for a ring, a last point repeating the first). */
function dedupe(part: readonly number[], ring: boolean): number[] {
  const out: number[] = [];
  for (let i = 0; i + 1 < part.length; i += 2) {
    const px = part[i] ?? 0;
    const py = part[i + 1] ?? 0;
    const n = out.length;
    if (n >= 2 && out[n - 2] === px && out[n - 1] === py) continue;
    out.push(px, py);
  }
  if (ring) {
    while (out.length >= 4 && out[0] === out[out.length - 2] && out[1] === out[out.length - 1]) {
      out.length -= 2;
    }
  }
  return out;
}

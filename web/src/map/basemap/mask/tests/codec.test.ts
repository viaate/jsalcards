// @vitest-environment node
/**
 * The vector tile codec the mask uses: geometry encoded as the Mapbox Vector
 * Tile specification's own examples encode it, tiles decoded and written
 * again unchanged, and geometry changed without touching ids or properties.
 */
import { describe, expect, it } from 'vitest';

import {
  LINE,
  POINT,
  POLYGON,
  decodeGeometry,
  decodeTile,
  encodeGeometry,
  encodeTile,
  newLayer,
  stringProperty,
} from '../mvt';
import { Reader, Writer, readPacked, unzigzag, zigzag } from '../protobuf';

/** A feature message's fields: id, tags, type and geometry, as numbers. */
function fields(raw: Uint8Array): {
  id?: number;
  tags: number[];
  type?: number;
  geometry: number[];
} {
  const reader = new Reader(raw);
  const out: { id?: number; tags: number[]; type?: number; geometry: number[] } = {
    tags: [],
    geometry: [],
  };
  for (let field = reader.next(); field !== null; field = reader.next()) {
    if (field.tag === 1) out.id = field.value;
    if (field.tag === 2) out.tags = readPacked(raw, field.value, field.valueEnd);
    if (field.tag === 3) out.type = field.value;
    if (field.tag === 4) out.geometry = readPacked(raw, field.value, field.valueEnd);
  }
  return out;
}

/** A layer with ids and properties, written field by field as OpenMapTiles tiles are. */
function propertiesLayer(): Uint8Array {
  const value = (text: string): Uint8Array => new Writer().string(1, text).finish();
  const feature = (id: number, tags: number[], type: number, geometry: number[]): Uint8Array =>
    new Writer().uint(1, id).packed(2, tags).uint(3, type).packed(4, geometry).finish();
  const layer = new Writer()
    .uint(15, 2)
    .string(1, 'water')
    .bytes(2, feature(7, [0, 0], POLYGON, encodeGeometry(POLYGON, [[0, 0, 10, 0, 10, 10, 0, 10]])))
    .bytes(2, feature(8, [0, 1, 1, 2], LINE, encodeGeometry(LINE, [[0, 0, 5, 5]])))
    .string(3, 'class')
    .string(3, 'name')
    .bytes(4, value('ocean'))
    .bytes(4, value('lake'))
    .bytes(4, value('Lake Erie'))
    .uint(5, 4096)
    .finish();
  return new Writer().bytes(3, layer).finish();
}

describe('protobuf', () => {
  it('writes and reads varints up to 2^53', () => {
    for (const value of [0, 1, 127, 128, 300, 2 ** 31, 2 ** 40 + 5, Number.MAX_SAFE_INTEGER]) {
      const bytes = new Writer().varint(value).finish();
      expect(new Reader(bytes).varint()).toBe(value);
    }
  });

  it('zigzags signed integers', () => {
    for (const value of [0, -1, 1, -64, 64, -4096, 12_000]) {
      expect(unzigzag(zigzag(value))).toBe(value);
    }
  });
});

describe('vector tiles', () => {
  it('encodes geometry as the specification examples do (section 4.3.5)', () => {
    expect(encodeGeometry(POINT, [[25, 17]])).toEqual([9, 50, 34]);
    expect(
      encodeGeometry(POINT, [
        [5, 7],
        [3, 2],
      ]),
    ).toEqual([17, 10, 14, 3, 9]);
    expect(encodeGeometry(LINE, [[2, 2, 2, 10, 10, 10]])).toEqual([9, 4, 4, 18, 0, 16, 16, 0]);
    expect(
      encodeGeometry(LINE, [
        [2, 2, 2, 10, 10, 10],
        [1, 1, 3, 5],
      ]),
    ).toEqual([9, 4, 4, 18, 0, 16, 16, 0, 9, 17, 17, 10, 4, 8]);
    expect(encodeGeometry(POLYGON, [[3, 6, 8, 12, 20, 34]])).toEqual([
      9, 6, 12, 18, 10, 12, 24, 44, 15,
    ]);
  });

  it('decodes geometry as parts, and encodes it back', () => {
    const parts = [
      [0, 0, 100, 0, 100, 100],
      [-50, 20, 4200, 30],
    ];
    expect(decodeGeometry(encodeGeometry(LINE, parts))).toEqual(parts);
    const points = [
      [5, 6],
      [7, 8],
    ];
    expect(decodeGeometry(encodeGeometry(POINT, points))).toEqual(points);
    // Rings drop the repeated closing point and repeated points; too-short parts go.
    expect(
      decodeGeometry(
        encodeGeometry(POLYGON, [
          [0, 0, 1, 0, 1, 0, 1, 1, 0, 0],
          [3, 3, 4, 4],
        ]),
      ),
    ).toEqual([[0, 0, 1, 0, 1, 1]]);
  });

  it('copies a tile unchanged, and reads string properties', () => {
    const tile = propertiesLayer();
    const [layer] = decodeTile(tile);
    expect(layer?.name).toBe('water');
    expect(layer?.keys).toEqual(['class', 'name']);
    const [polygon, line] = layer?.features ?? [];
    if (layer === undefined || polygon === undefined || line === undefined)
      throw new Error('no features');
    expect(stringProperty(layer, polygon, 'class')).toBe('ocean');
    expect(stringProperty(layer, line, 'class')).toBe('lake');
    expect(stringProperty(layer, line, 'name')).toBe('Lake Erie');
    expect(stringProperty(layer, polygon, 'name')).toBeNull();
    const copy = encodeTile([{ fields: layer.fields, features: layer.features.map((f) => f.raw) }]);
    const read = (bytes: Uint8Array) =>
      decodeTile(bytes).map((l) => ({
        name: l.name,
        extent: l.extent,
        keys: l.keys,
        values: l.values,
        features: l.features.map((f) => fields(f.raw)),
      }));
    expect(read(copy)).toEqual(read(tile));
    expect(copy.length).toBe(tile.length);
  });

  it('changes a feature geometry and keeps its id, type and properties', () => {
    const [layer] = decodeTile(propertiesLayer());
    const line = layer?.features[1];
    if (layer === undefined || line === undefined) throw new Error('no line');
    const changed = line.withParts([[1, 2, 3, 4, 9, 9]]);
    if (changed === null) throw new Error('no geometry written');
    const tile = encodeTile([{ fields: layer.fields, features: [changed] }]);
    const [read] = decodeTile(tile);
    const feature = read?.features[0];
    if (read === undefined || feature === undefined) throw new Error('no feature');
    expect(fields(feature.raw)).toMatchObject({ id: 8, type: LINE, tags: [0, 1, 1, 2] });
    expect(stringProperty(read, feature, 'name')).toBe('Lake Erie');
    expect(feature.parts()).toEqual([[1, 2, 3, 4, 9, 9]]);
  });

  it('writes no feature with nothing left of its geometry: MapLibre fails a tile holding one', () => {
    const [layer] = decodeTile(propertiesLayer());
    const line = layer?.features[1];
    if (layer === undefined || line === undefined) throw new Error('no line');
    // A line whose every part is one point, repeated or alone.
    expect(line.withParts([[5, 5, 5, 5], [7, 7], []])).toBeNull();
    expect(line.withParts([])).toBeNull();
    // Beside a part with two points, those are left out, and the rest written.
    const kept = line.withParts([
      [5, 5, 5, 5],
      [1, 2, 3, 4],
    ]);
    if (kept === null) throw new Error('nothing written');
    const [read] = decodeTile(encodeTile([{ fields: layer.fields, features: [kept] }]));
    expect(read?.features[0]?.parts()).toEqual([[1, 2, 3, 4]]);
    // New layers leave out such features: a ring of two points, a line of one.
    const tile = encodeTile([
      newLayer('us_mask', [
        { type: POLYGON, parts: [[10, 10, 11, 11, 10, 10]] },
        { type: POLYGON, parts: [[0, 0, 8, 0, 8, 8]] },
      ]),
      newLayer('us_border', [{ type: LINE, parts: [[3, 3, 3, 3]] }]),
    ]);
    expect(
      decodeTile(tile).map((found) => [found.name, found.features.map((f) => f.parts())]),
    ).toEqual([
      ['us_mask', [[[0, 0, 8, 0, 8, 8]]]],
      ['us_border', []],
    ]);
  });

  it('writes new layers with an extent, a version and features of their own', () => {
    const tile = encodeTile([
      newLayer('us_mask', [
        { type: POLYGON, parts: [[-128, -128, 4224, -128, 4224, 4224, -128, 4224]] },
      ]),
      newLayer('us_border', [{ type: LINE, parts: [[0, 0, 4096, 4096]] }]),
      newLayer('empty', []),
    ]);
    const [mask] = decodeTile(tile);
    expect(mask?.extent).toBe(4096);
    expect(fields(mask?.features[0]?.raw ?? new Uint8Array()).type).toBe(POLYGON);
    // Version 2, as the specification requires of every layer.
    const version = mask?.fields
      .map((field) => new Reader(field).next())
      .find((f) => f?.tag === 15);
    expect(version?.value).toBe(2);
    expect(decodeTile(tile).map((layer) => [layer.name, layer.features.length])).toEqual([
      ['us_mask', 1],
      ['us_border', 1],
      ['empty', 0],
    ]);
  });
});

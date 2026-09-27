// @vitest-environment node
/**
 * The school tiles as the workers serve them: read from the archive, and
 * every school's name put in the form the page shows, nothing else changed.
 * The last test reads the pipeline's own schools.pmtiles when it is there.
 */
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

import { describe, expect, it, vi } from 'vitest';

import { SCHOOLS_TILE_LAYER, SCHOOL_TILES_PROTOCOL } from '../ids';
import { ArchiveReader } from '../mask/pmtiles';
import { decodeTile, stringProperty } from '../mask/mvt';
import type { Layer } from '../mask/mvt';
import { Writer, zigzag } from '../mask/protobuf';
import { schoolTileLoader, showSchoolNames } from '../school-tiles';
import { schoolTilesTemplate } from '../schools';

interface School {
  readonly index: number;
  readonly id: string;
  readonly name: string;
  readonly kind: number;
}

/** A tile as tippecanoe writes the schools layer: id, name and kind, values shared. */
function schoolTile(schools: readonly School[], otherLayer = false): Uint8Array {
  const values: (string | number)[] = [];
  const valueOf = (value: string | number): number => {
    const at = values.indexOf(value);
    if (at >= 0) return at;
    values.push(value);
    return values.length - 1;
  };
  const layer = new Writer().uint(15, 2).string(1, SCHOOLS_TILE_LAYER);
  schools.forEach((school, i) => {
    const tags = [0, valueOf(school.id), 1, valueOf(school.name), 2, valueOf(school.kind)];
    const feature = new Writer()
      .uint(1, school.index)
      .packed(2, tags)
      .uint(3, 1)
      .packed(4, [9, zigzag(100 + i * 10), zigzag(200)])
      .finish();
    layer.bytes(2, feature);
  });
  for (const key of ['id', 'name', 'kind']) layer.string(3, key);
  for (const value of values) {
    const message =
      typeof value === 'string'
        ? new Writer().string(1, value).finish()
        : new Writer().uint(5, value).finish();
    layer.bytes(4, message);
  }
  layer.uint(5, 4096);
  const tile = new Writer().bytes(3, layer.finish());
  if (otherLayer) {
    const other = new Writer().uint(15, 2).string(1, 'other').string(3, 'name');
    other.bytes(4, new Writer().string(1, 'LEFT ALONE SCH').finish());
    other.bytes(2, new Writer().packed(2, [0, 0]).uint(3, 1).packed(4, [9, 2, 2]).finish());
    tile.bytes(3, other.finish());
  }
  return tile.finish();
}

function schoolsLayer(tile: Uint8Array): Layer {
  const layer = decodeTile(tile).find((candidate) => candidate.name === SCHOOLS_TILE_LAYER);
  if (layer === undefined) throw new Error('no schools layer');
  return layer;
}

/** Each school's id and name, in the tile's order. */
function names(tile: Uint8Array): [string | null, string | null][] {
  const layer = schoolsLayer(tile);
  return layer.features.map((feature) => [
    stringProperty(layer, feature, 'id'),
    stringProperty(layer, feature, 'name'),
  ]);
}

const PEMBROKE_HILL: School = {
  index: 109674,
  id: 'A1902690',
  name: 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
  kind: 1,
};
const ROSS: School = { index: 80000, id: '421866004476', name: 'Ross El Sch', kind: 0 };

describe('school names in the tiles', () => {
  it('are shown as the page shows them, and nothing else changes', () => {
    const tile = schoolTile([PEMBROKE_HILL, ROSS]);
    const shown = showSchoolNames(tile);
    expect(names(shown)).toEqual([
      ['A1902690', 'The Pembroke Hill School - Wornall Campus'],
      ['421866004476', 'Ross Elementary School'],
    ]);
    const before = schoolsLayer(tile);
    const after = schoolsLayer(shown);
    expect(after.keys).toEqual(before.keys);
    expect(after.extent).toBe(before.extent);
    after.features.forEach((feature, i) => {
      expect(feature.parts()).toEqual(before.features[i]?.parts());
      expect(feature.type).toBe(before.features[i]?.type);
      expect(feature.tags()).toEqual(before.features[i]?.tags());
    });
    // Kind stays a number.
    expect(after.values[after.features[0]?.tags()[5] ?? -1]).toBeNull();
  });

  it('give a school its own name where it reads differently from a school sharing it', () => {
    const name = 'NORTHEAST MS REGIONAL ALTERNATIVE';
    const tile = schoolTile([
      { index: 1, id: '280019401239', name, kind: 0 },
      { index: 2, id: 'A0000001', name, kind: 1 },
      { index: 3, id: '280019401240', name, kind: 0 },
    ]);
    expect(names(showSchoolNames(tile))).toEqual([
      ['280019401239', 'Northeast MS Regional Alternative'],
      ['A0000001', 'Northeast Middle School Regional Alternative'],
      ['280019401240', 'Northeast MS Regional Alternative'],
    ]);
  });

  it('keep a value another property shares, and a school whose name reads as written', () => {
    const tile = schoolTile([
      // Mississippi's MS stays: this name reads as written there, and differently elsewhere.
      { index: 1, id: '280000000001', name: 'Jackson MS', kind: 0 },
      { index: 2, id: '420000000002', name: 'Jackson MS', kind: 0 },
      // A name that is also another school's id.
      { index: 3, id: 'OAK SCH', name: 'ELM SCH', kind: 0 },
      { index: 4, id: 'A0000004', name: 'OAK SCH', kind: 1 },
    ]);
    expect(names(showSchoolNames(tile))).toEqual([
      ['280000000001', 'Jackson MS'],
      ['420000000002', 'Jackson Middle School'],
      ['OAK SCH', 'Elm School'],
      ['A0000004', 'Oak School'],
    ]);
  });

  it('leave other layers as they are', () => {
    const shown = showSchoolNames(schoolTile([ROSS], true));
    const other = decodeTile(shown).find((layer) => layer.name === 'other');
    expect(other?.values).toEqual(['LEFT ALONE SCH']);
  });
});

describe('the school tile protocol', () => {
  const ARCHIVE = 'https://snow.test/data/schools/schools.0123456789.pmtiles';
  const request = (url: string) => ({ url }) as Parameters<ReturnType<typeof schoolTileLoader>>[0];
  const controller = new AbortController();

  it('reads each tile from the archive its URL names, one reader per archive', async () => {
    const tile = vi.fn((z: number, x: number, y: number) =>
      Promise.resolve(z === 14 && x === 3789 && y === 6209 ? schoolTile([PEMBROKE_HILL]) : null),
    );
    const open = vi.fn(() => ({ tile }) as unknown as ArchiveReader);
    const load = schoolTileLoader(open);
    const template = schoolTilesTemplate(ARCHIVE);
    expect(template).toBe(`${SCHOOL_TILES_PROTOCOL}://${ARCHIVE}/{z}/{x}/{y}`);
    const url = (z: number, x: number, y: number): string =>
      template.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y));

    const found = await load(request(url(14, 3789, 6209)), controller);
    expect(names(new Uint8Array(found.data as ArrayBuffer))).toEqual([
      ['A1902690', 'The Pembroke Hill School - Wornall Campus'],
    ]);
    const empty = await load(request(url(14, 0, 0)), controller);
    expect((empty.data as ArrayBuffer).byteLength).toBe(0);
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith(ARCHIVE);
    expect(tile).toHaveBeenCalledWith(14, 3789, 6209);
    await expect(load(request('snowlight-schools://nothing'), controller)).rejects.toThrow(
      /unexpected request/,
    );
  });
});

const PIPELINE_TILES = fileURLToPath(
  new URL('../../../../../pipeline/out/site-data/schools/schools.pmtiles', import.meta.url),
);

/** The tile at zoom `z` holding a place. */
function tileAt(lon: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  const rad = (lat * Math.PI) / 180;
  return [
    Math.floor(((lon + 180) / 360) * n),
    Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n),
  ];
}

describe.skipIf(!existsSync(PIPELINE_TILES))('the pipeline’s school tiles', () => {
  it('name Pembroke Hill as the page does, where the directory puts it', async () => {
    const bytes = readFileSync(PIPELINE_TILES);
    const archive = new ArchiveReader(
      (offset, length) => Promise.resolve(new Uint8Array(bytes.subarray(offset, offset + length))),
      (data) => Promise.resolve(new Uint8Array(gunzipSync(data))),
      { keepTiles: false },
    );
    for (const z of [11, 13, 14]) {
      const [x, y] = tileAt(-94.593001, 39.03606, z);
      const tile = await archive.tile(z, x, y);
      expect(tile).not.toBeNull();
      const shown = names(showSchoolNames(tile ?? new Uint8Array()));
      expect(shown).toContainEqual(['A1902690', 'The Pembroke Hill School - Wornall Campus']);
    }
  });
});

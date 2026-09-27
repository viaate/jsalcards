// @vitest-environment node
/**
 * Street tiles cut to the US (rewrite.ts), and the worker's protocol handler
 * that reads the mask and cuts them (street-tiles.ts), on tiles shaped like
 * OpenFreeMap's.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { streetTileLoader } from '../../street-tiles';
import { US_MASK_FILE } from '../../us-mask';
import { BORDER_LAYER, MASK_BOX, MASK_LAYER } from '../format';
import { boxRing, reverseRing, ringArea } from '../geometry';
import {
  EXTENT,
  LINE,
  POINT,
  POLYGON,
  decodeTile,
  encodeGeometry,
  encodeTile,
  stringProperty,
} from '../mvt';
import { Reader, Writer } from '../protobuf';
import { maskStreetTile } from '../rewrite';
import type { TileMask } from '../source';

interface TestFeature {
  readonly id: number;
  readonly type: number;
  readonly parts: number[][];
  readonly name: string;
}

/** A layer as OpenMapTiles writes one: ids, a name and a class on every feature. */
function layer(name: string, features: readonly TestFeature[], featureClass = 'test'): Uint8Array {
  const writer = new Writer().uint(15, 2).string(1, name);
  const names = [...new Set(features.map((f) => f.name))];
  for (const feature of features) {
    writer.bytes(
      2,
      new Writer()
        .uint(1, feature.id)
        .packed(2, [0, 0, 1, 1 + names.indexOf(feature.name)])
        .uint(3, feature.type)
        .packed(4, encodeGeometry(feature.type, feature.parts))
        .finish(),
    );
  }
  writer.string(3, 'class').string(3, 'name');
  writer.bytes(4, new Writer().string(1, featureClass).finish());
  for (const text of names) writer.bytes(4, new Writer().string(1, text).finish());
  return writer.uint(5, EXTENT).finish();
}

function tile(...layers: Uint8Array[]): Uint8Array {
  const writer = new Writer();
  for (const bytes of layers) writer.bytes(3, bytes);
  return writer.finish();
}

/** The bytes in an ArrayBuffer of their own, as fetch gives them. */
function copyBuffer(bytes: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(bytes.length);
  new Uint8Array(buffer).set(bytes);
  return buffer;
}

/** Outside the US north of y = 2000, as a mask tile's rings come. */
const NORTH = [-128, -128, 4224, -128, 4224, 2000, -128, 2000];
const MASK: TileMask = {
  kind: 'mixed',
  rings: [ringArea(NORTH) > 0 ? NORTH : reverseRing(NORTH)],
  border: [[-128, 2000, 4224, 2000]],
};

const STREET = tile(
  layer('place', [
    { id: 1, type: POINT, parts: [[1000, 3000]], name: 'Detroit' },
    { id: 2, type: POINT, parts: [[1000, 500]], name: 'Windsor' },
    {
      id: 3,
      type: POINT,
      parts: [
        [1500, 3500],
        [1500, 1500],
      ],
      name: 'Twins',
    },
  ]),
  layer('transportation', [
    { id: 10, type: LINE, parts: [[500, 3000, 500, 1000]], name: 'Bridge' },
    { id: 11, type: LINE, parts: [[100, 3000, 3000, 3500]], name: 'Home Road' },
    { id: 12, type: LINE, parts: [[100, 100, 3000, 900]], name: 'Away Road' },
  ]),
  layer('building', [
    { id: 20, type: POLYGON, parts: [[100, 100, 200, 100, 200, 200, 100, 200]], name: 'Away' },
    { id: 21, type: POLYGON, parts: [[100, 3000, 200, 3000, 200, 3100, 100, 3100]], name: 'Home' },
    { id: 22, type: POLYGON, parts: [[100, 1500, 400, 1500, 400, 2500, 100, 2500]], name: 'Both' },
  ]),
  // The sea east of x = 3000: the border stops at it.
  layer(
    'water',
    [
      {
        id: 30,
        type: POLYGON,
        parts: [[3000, -128, 4224, -128, 4224, 4224, 3000, 4224]],
        name: 'Sea',
      },
    ],
    'ocean',
  ),
);

/** A tile's layers: each feature's id, name and geometry. */
function read(bytes: Uint8Array) {
  const out: Record<string, { id: number | undefined; name: unknown; parts: number[][] }[]> = {};
  for (const found of decodeTile(bytes)) {
    out[found.name] = found.features.map((feature) => {
      let id: number | undefined;
      const reader = new Reader(feature.raw);
      for (let field = reader.next(); field !== null; field = reader.next()) {
        if (field.tag === 1) id = field.value;
      }
      return {
        id,
        name: stringProperty(found, feature, 'name') ?? undefined,
        parts: feature.parts(),
      };
    });
  }
  return out;
}

describe('a street tile the border crosses', () => {
  const cut = read(maskStreetTile(STREET, MASK));

  it('drops names outside the US, and keeps those inside', () => {
    expect(cut.place?.map((f) => f.name)).toEqual(['Detroit', 'Twins']);
    expect(cut.place?.[1]?.parts).toEqual([[1500, 3500]]);
    expect(cut.place?.[0]?.id).toBe(1);
  });

  it('cuts roads at the border, and keeps only their US part', () => {
    const roads = cut.transportation ?? [];
    expect(roads.map((f) => f.name)).toEqual(['Bridge', 'Home Road']);
    expect(roads[0]?.parts).toEqual([[500, 3000, 500, 2000]]);
    expect(roads[1]?.parts).toEqual([[100, 3000, 3000, 3500]]);
  });

  it('drops areas wholly outside, and leaves the rest for the mask to hide', () => {
    expect(cut.building?.map((f) => f.name)).toEqual(['Home', 'Both']);
  });

  it('adds the mask and the border line, the line stopping at the sea', () => {
    expect(cut[MASK_LAYER]).toHaveLength(1);
    expect(cut[BORDER_LAYER]?.[0]?.parts).toEqual([[-128, 2000, 3000, 2000]]);
  });

  it('comes back whole inside the US, and empty outside it', () => {
    expect(maskStreetTile(STREET, { kind: 'inside', rings: [], border: [] })).toBe(STREET);
    expect(maskStreetTile(STREET, { kind: 'outside', rings: [], border: [] })).toHaveLength(0);
  });
});

describe('the street tile protocol', () => {
  const archive = readFileSync(resolve(import.meta.dirname, '../../../../../public', US_MASK_FILE));
  const MASK_URL = 'https://snowlight.test/geo/us-mask.pmtiles';

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Serves the archive by range, as the site does. */
  function serveArchive(): string[] {
    const requested: string[] = [];
    vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
      requested.push(url);
      if (url !== MASK_URL) return Promise.resolve(new Response(null, { status: 404 }));
      const range = /bytes=(\d+)-(\d+)/.exec(new Headers(init?.headers).get('range') ?? '');
      const start = Number(range?.[1] ?? 0);
      const end = Number(range?.[2] ?? archive.length - 1);
      return Promise.resolve(new Response(archive.subarray(start, end + 1), { status: 206 }));
    });
    return requested;
  }

  function locate(lon: number, lat: number, z: number) {
    const world = 2 ** z;
    const sin = Math.sin((lat * Math.PI) / 180);
    const mx = ((lon + 180) / 360) * world;
    const my = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * world;
    const x = Math.floor(mx);
    const y = Math.floor(my);
    return { x, y, px: Math.round((mx - x) * EXTENT), py: Math.round((my - y) * EXTENT) };
  }

  it('answers tiles outside the US with nothing, without asking for them', async () => {
    serveArchive();
    const loadTile = vi.fn();
    const load = streetTileLoader(MASK_URL, loadTile);
    // Toronto, at street zoom.
    const { x, y } = locate(-79.38, 43.65, 14);
    const response = await load(
      { url: `openfreemap://planet/14/${String(x)}/${String(y)}` },
      new AbortController(),
    );
    expect((response.data as ArrayBuffer).byteLength).toBe(0);
    expect(loadTile).not.toHaveBeenCalled();
  });

  it('passes tiles inside the US through untouched', async () => {
    serveArchive();
    const street = { data: copyBuffer(STREET), cacheControl: 'max-age=60', expires: null };
    const load = streetTileLoader(MASK_URL, () => Promise.resolve(street));
    // Kansas City.
    const { x, y } = locate(-94.593, 39.036, 14);
    const response = await load(
      { url: `openfreemap://planet/14/${String(x)}/${String(y)}` },
      new AbortController(),
    );
    expect(response).toBe(street);
  });

  it('cuts a tile at the border: Windsor goes, Detroit stays', async () => {
    const requested = serveArchive();
    const detroit = locate(-83.0458, 42.3314, 12);
    const windsor = locate(-83.0364, 42.3149, 12);
    expect([windsor.x, windsor.y]).toEqual([detroit.x, detroit.y]);
    const street = tile(
      layer('place', [
        { id: 1, type: POINT, parts: [[detroit.px, detroit.py]], name: 'Detroit' },
        { id: 2, type: POINT, parts: [[windsor.px, windsor.py]], name: 'Windsor' },
      ]),
    );
    const load = streetTileLoader(MASK_URL, () =>
      Promise.resolve({ data: copyBuffer(street), cacheControl: null, expires: null }),
    );
    const response = await load(
      { url: `openfreemap://planet/12/${String(detroit.x)}/${String(detroit.y)}` },
      new AbortController(),
    );
    const cut = read(new Uint8Array(response.data as ArrayBuffer));
    expect(cut.place?.map((f) => f.name)).toEqual(['Detroit']);
    expect(cut[MASK_LAYER]).toHaveLength(1);
    expect(cut[BORDER_LAYER]?.length).toBe(1);
    // Only the mask archive was fetched, by range.
    expect(new Set(requested)).toEqual(new Set([MASK_URL]));
  });

  it('keeps the mask tile layers MapLibre draws inside the tile box', () => {
    const mask = maskStreetTile(encodeTile([]), {
      kind: 'mixed',
      rings: [boxRing(MASK_BOX), reverseRing([0, 0, 100, 0, 100, 100, 0, 100])],
      border: [],
    });
    const cut = read(mask);
    expect(cut[MASK_LAYER]?.[0]?.parts).toHaveLength(2);
  });
});

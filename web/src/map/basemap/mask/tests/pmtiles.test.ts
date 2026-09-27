// @vitest-environment node
/**
 * The PMTiles writer and reader, checked against the reference
 * implementation (the pmtiles package): tile ids, a small archive, and one
 * large enough to need leaf directories.
 */
import { gunzipSync, gzipSync } from 'node:zlib';

import { PMTiles, zxyToTileId as referenceTileId } from 'pmtiles';
import type { RangeResponse, Source } from 'pmtiles';
import { describe, expect, it } from 'vitest';

import { ArchiveReader, ROOT_BYTES, decodeHeader, writeArchive, zxyToTileId } from '../pmtiles';
import type { ArchiveTile } from '../pmtiles';

const OPTIONS = {
  metadata: { name: 'test' },
  bounds: [-125, 24, -66, 50] as const,
  center: [-98, 39, 7] as const,
  gzip: (bytes: Uint8Array) => gzipSync(bytes),
};

function source(bytes: Uint8Array): Source {
  return {
    getKey: () => 'memory',
    getBytes: (offset: number, length: number): Promise<RangeResponse> =>
      Promise.resolve({ data: bytes.slice(offset, offset + length).buffer }),
  };
}

function reader(bytes: Uint8Array): ArchiveReader {
  return new ArchiveReader(
    (offset, length) => Promise.resolve(bytes.subarray(offset, offset + length)),
    (data) => Promise.resolve(gunzipSync(data)),
  );
}

describe('tile ids', () => {
  it('match the reference implementation', () => {
    for (let z = 0; z <= 14; z++) {
      const n = 2 ** z;
      for (const [x, y] of [
        [0, 0],
        [n - 1, 0],
        [0, n - 1],
        [n - 1, n - 1],
        [Math.floor(n / 3), Math.floor((2 * n) / 3)],
        [Math.floor(n * 0.27), Math.floor(n * 0.37)],
      ] as const) {
        expect(zxyToTileId(z, x, y), `${String(z)}/${String(x)}/${String(y)}`).toBe(
          referenceTileId(z, x, y),
        );
      }
    }
  });
});

describe('archives', () => {
  const tile = (text: string): Uint8Array => new TextEncoder().encode(text);

  it('are read back by the reference reader and by ours', async () => {
    const tiles: ArchiveTile[] = [
      { z: 7, x: 30, y: 45, bytes: tile('a') },
      { z: 7, x: 31, y: 45, bytes: tile('b') },
      { z: 8, x: 60, y: 90, bytes: tile('a') },
      { z: 12, x: 1103, y: 1515, bytes: tile('mixed') },
    ];
    const archive = writeArchive(tiles, OPTIONS);
    const header = decodeHeader(archive);
    expect(header.minZoom).toBe(7);
    expect(header.maxZoom).toBe(12);
    expect(header.tileContents).toBe(3);
    const reference = new PMTiles(source(archive));
    expect(await reference.getMetadata()).toEqual({ name: 'test' });
    const ours = reader(archive);
    for (const { z, x, y, bytes } of tiles) {
      const got = await reference.getZxy(z, x, y);
      expect(new Uint8Array(got?.data ?? new ArrayBuffer(0))).toEqual(bytes);
      expect(await ours.tile(z, x, y)).toEqual(bytes);
    }
    expect(await reference.getZxy(7, 29, 45)).toBeUndefined();
    expect(await ours.tile(7, 29, 45)).toBeNull();
    expect(await ours.tile(13, 0, 0)).toBeNull();
  });

  it('split their directory into leaves when it would not fit in the first read', async () => {
    const tiles: ArchiveTile[] = [];
    for (let x = 0; x < 512; x++) {
      for (let y = 0; y < 512; y++) {
        // Scattered tiles of scattered sizes, none alike: a directory that compresses badly.
        if ((x * 7919 + y * 104_729) % 7 > 2) continue;
        tiles.push({
          z: 9,
          x,
          y,
          bytes: tile(`${String(x)},${String(y)}`.repeat(1 + ((x * 31 + y * 17) % 13))),
        });
      }
    }
    const archive = writeArchive(tiles, OPTIONS);
    const header = decodeHeader(archive);
    expect(header.leafLength).toBeGreaterThan(0);
    expect(header.rootOffset + header.rootLength).toBeLessThanOrEqual(ROOT_BYTES);
    const reference = new PMTiles(source(archive));
    const ours = reader(archive);
    for (const [x, y] of [
      [0, 0],
      [511, 511],
      [64, 3],
      [6, 99],
    ] as const) {
      const expected = tile(`${String(x)},${String(y)}`.repeat(1 + ((x * 31 + y * 17) % 13)));
      expect(new Uint8Array((await reference.getZxy(9, x, y))?.data ?? new ArrayBuffer(0))).toEqual(
        expected,
      );
      expect(await ours.tile(9, x, y)).toEqual(expected);
    }
    expect(await ours.tile(9, 3, 0)).toBeNull();
  });

  it('store a tile repeated along the curve once, as one run', () => {
    const same = tile('same');
    const tiles: ArchiveTile[] = [];
    for (let x = 0; x < 4; x++) for (let y = 0; y < 4; y++) tiles.push({ z: 2, x, y, bytes: same });
    const header = decodeHeader(writeArchive(tiles, OPTIONS));
    expect(header.tileContents).toBe(1);
    expect(header.tileEntries).toBe(1);
    expect(header.addressedTiles).toBe(16);
  });
});

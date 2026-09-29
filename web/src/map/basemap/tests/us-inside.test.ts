// @vitest-environment node
/**
 * The street tiles wholly inside the US, listed when the site is built
 * (tools/us-mask.ts): exactly the ones the mask itself says need no cutting,
 * at its first zoom and every zoom under it, so asking for them before the
 * mask is in changes nothing that is drawn.
 */
import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';

import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import { ArchiveReader } from '../mask/pmtiles';
import { tileMask } from '../mask/source';
import { insideUs } from '../us-inside';
import { US_MASK_FILE } from '../us-mask';

const archive = readFileSync(new URL(`../../../../public/${US_MASK_FILE}`, import.meta.url));
const reader = new ArchiveReader(
  (offset, length) => Promise.resolve(new Uint8Array(archive.subarray(offset, offset + length))),
  (bytes) => Promise.resolve(new Uint8Array(gunzipSync(bytes))),
);

/** The tile holding a point at zoom z. */
function tileAt(lat: number, lon: number, z: number): [number, number] {
  const count = 2 ** z;
  return [Math.floor(mercatorXFromLng(lon) * count), Math.floor(mercatorYFromLat(lat) * count)];
}

describe('street tiles wholly inside the US', () => {
  it('are exactly the ones the mask leaves whole, at its first zoom', async () => {
    const { header } = await reader.start();
    const [minLon, minLat, maxLon, maxLat] = header.bounds;
    const [west, north] = tileAt(maxLat, minLon, 7);
    const [east, south] = tileAt(minLat, maxLon, 7);
    let listed = 0;
    for (let y = north - 1; y <= south + 1; y++) {
      for (let x = west - 1; x <= east + 1; x++) {
        const mask = await tileMask(reader, 7, x, y);
        expect(insideUs(7, x, y), `7/${String(x)}/${String(y)}`).toBe(mask.kind === 'inside');
        if (mask.kind === 'inside') listed++;
      }
    }
    // Most of the country.
    expect(listed).toBeGreaterThan(100);
  });

  it('and every tile under them, to street zoom, the mask leaving them whole too', async () => {
    // Kansas City, from its first-zoom tile to street zoom.
    for (const z of [7, 9, 12, 14]) {
      const [x, y] = tileAt(39.036, -94.593, z);
      expect(insideUs(z, x, y)).toBe(true);
      expect((await tileMask(reader, z, x, y)).kind).toBe('inside');
    }
  });

  it('never include a tile the border or the coast crosses, nor one below the first zoom', () => {
    for (const [lat, lon] of [
      [42.32, -83.05], // Detroit, on the river with Windsor.
      [32.55, -117.05], // San Diego, on the fence with Tijuana.
      [25.82, -80.22], // Miami, on the sea.
    ] as const) {
      const [x, y] = tileAt(lat, lon, 12);
      expect(insideUs(12, x, y)).toBe(false);
    }
    const [x, y] = tileAt(39.036, -94.593, 6);
    expect(insideUs(6, x, y)).toBe(false);
  });
});

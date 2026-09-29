/**
 * What the build makes of the US mask archive (src/map/basemap/us-mask.ts):
 *
 * - a copy of it under a name that never changes
 *   (src/map/basemap/us-mask-alias.ts), for a page from an older build whose
 *   mask file a newer build has replaced (build only: the dev server serves
 *   public/ as it is, and a page there is never older than its files);
 * - the module `virtual:snowlight/us-inside`: the mask's first-zoom tiles that
 *   are wholly inside the US (src/map/basemap/us-inside.ts). A street tile
 *   under one of them is drawn as OpenFreeMap sends it, so it needs no mask,
 *   and can come before the mask does.
 *
 * The archive is read with the pmtiles package. A mask tile wholly inside the
 * US is one layer, us_mask, with no features in it (src/map/basemap/mask/
 * format.ts); such a tile is never cut further, so every tile under it is
 * wholly inside too (mask/pyramid.ts). src/map/basemap/tests/us-inside.test.ts
 * checks the list against the map's own reading of the archive.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { PMTiles } from 'pmtiles';
import type { Plugin } from 'vite';

import { US_MASK_ALIAS } from '../src/map/basemap/us-mask-alias.ts';
import { US_MASK_FILE } from '../src/map/basemap/us-mask.ts';

export const US_INSIDE_MODULE = 'virtual:snowlight/us-inside';
const RESOLVED_ID = `\0${US_INSIDE_MODULE}`;

/** The mask's first zoom (mask/format.ts MASK_MIN_ZOOM). */
const FIRST_ZOOM = 7;
/** The mask's own layer (mask/format.ts MASK_LAYER). */
const MASK_LAYER = 'us_mask';

/** A protobuf message's fields, as [field number, wire type, value or bytes]. */
function fields(bytes: Uint8Array): [number, number, Uint8Array | number][] {
  const out: [number, number, Uint8Array | number][] = [];
  let at = 0;
  const varint = (): number => {
    let value = 0;
    let shift = 0;
    for (;;) {
      const byte = bytes[at++] ?? 0;
      value += (byte & 0x7f) * 2 ** shift;
      if (byte < 0x80) return value;
      shift += 7;
    }
  };
  while (at < bytes.length) {
    const key = varint();
    const field = Math.floor(key / 8);
    const wire = key % 8;
    if (wire === 0) out.push([field, wire, varint()]);
    else if (wire === 2) {
      const length = varint();
      out.push([field, wire, bytes.subarray(at, at + length)]);
      at += length;
    } else if (wire === 5) at += 4;
    else if (wire === 1) at += 8;
    else throw new Error(`us-mask: wire type ${String(wire)} in a mask tile`);
  }
  return out;
}

/** Whether a mask tile is wholly inside the US: one us_mask layer with no features. */
export function wholeInside(tile: Uint8Array): boolean {
  const layers = fields(tile).filter(([field]) => field === 3);
  if (layers.length !== 1) return false;
  const [, , layer] = layers[0] ?? [0, 0, 0];
  if (!(layer instanceof Uint8Array)) return false;
  const parts = fields(layer);
  const name = parts.find(([field]) => field === 1)?.[2];
  const named = name instanceof Uint8Array && new TextDecoder().decode(name) === MASK_LAYER;
  return named && !parts.some(([field]) => field === 2);
}

/**
 * The first-zoom tiles of the archive at `file` wholly inside the US, as runs
 * along each row: [y, first x, last x].
 */
export async function insideRuns(file: string): Promise<[number, number, number][]> {
  const bytes = readFileSync(file);
  const archive = new PMTiles({
    getKey: () => file,
    getBytes: (offset: number, length: number) =>
      Promise.resolve({
        data: bytes.buffer.slice(bytes.byteOffset + offset, bytes.byteOffset + offset + length),
      }),
  });
  const header = await archive.getHeader();
  const count = 2 ** FIRST_ZOOM;
  const lonX = (lon: number): number => Math.floor(((lon + 180) / 360) * count);
  const latY = (lat: number): number => {
    const sin = Math.sin((lat * Math.PI) / 180);
    return Math.floor((0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * count);
  };
  const runs: [number, number, number][] = [];
  for (let y = latY(header.maxLat); y <= latY(header.minLat); y++) {
    let start = -1;
    for (let x = lonX(header.minLon); x <= lonX(header.maxLon) + 1; x++) {
      const tile = x <= lonX(header.maxLon) ? await archive.getZxy(FIRST_ZOOM, x, y) : undefined;
      const inside = tile !== undefined && wholeInside(new Uint8Array(tile.data));
      if (inside && start < 0) start = x;
      if (!inside && start >= 0) {
        runs.push([y, start, x - 1]);
        start = -1;
      }
    }
  }
  return runs;
}

export function usMask(): Plugin {
  let publicDir = '';
  let building = false;
  return {
    name: 'snowlight:us-mask',
    configResolved(config) {
      publicDir = config.publicDir;
      building = config.command === 'build';
    },
    resolveId(id) {
      return id === US_INSIDE_MODULE ? RESOLVED_ID : null;
    },
    async load(id) {
      if (id !== RESOLVED_ID) return null;
      const file = path.join(publicDir, US_MASK_FILE);
      const runs = publicDir === '' ? [] : await insideRuns(file);
      return [
        `export const US_INSIDE_ZOOM = ${String(FIRST_ZOOM)};`,
        `export const US_INSIDE_RUNS = ${JSON.stringify(runs)};`,
        '',
      ].join('\n');
    },
    generateBundle() {
      if (!building || publicDir === '') return;
      this.emitFile({
        type: 'asset',
        fileName: US_MASK_ALIAS,
        source: readFileSync(path.join(publicDir, US_MASK_FILE)),
      });
    },
  };
}

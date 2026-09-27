// @vitest-environment node
/**
 * The mask builder's tiling (pyramid.ts), on a made-up country: one degree
 * square, whose north edge is a border and whose other edges are out at sea.
 * The real archive is checked place by place in us-mask.test.ts.
 */
import { describe, expect, it } from 'vitest';

import { BORDER_LAYER, MASK_BOX, MASK_LAYER } from '../format';
import { MaskIndex } from '../geometry';
import { EXTENT, decodeTile } from '../mvt';
import { BORDER_FLAG, INSIDE_TILE, OUTSIDE_TILE, buildPyramid } from '../pyramid';
import type { ArchiveTile } from '../pmtiles';
import { maskFromTile } from '../source';

const WEST = -100;
const EAST = -97;
const SOUTH = 38;
const NORTH = 41;

/** The square, with its north edge's vertices on the border, densified so the border has vertices. */
function square(): { coords: number[]; flags: Uint8Array; hole: boolean } {
  const coords: number[] = [];
  const flags: number[] = [];
  const steps = 20;
  // North edge, west to east: the border.
  for (let i = 0; i <= steps; i++) {
    coords.push(WEST + ((EAST - WEST) * i) / steps, NORTH);
    flags.push(BORDER_FLAG);
  }
  // East, south and west edges: at sea.
  coords.push(EAST, SOUTH, WEST, SOUTH);
  flags.push(0, 0);
  return { coords, flags: Uint8Array.from(flags), hole: false };
}

const { tiles } = buildPyramid([square()], {
  minZoom: 7,
  borderMaxZoom: 10,
  seaMaxZoom: 8,
  borderTolerance: () => 0.5,
  seaTolerance: () => 16,
});

function find(z: number, x: number, y: number): ArchiveTile | undefined {
  return tiles.find((tile) => tile.z === z && tile.x === x && tile.y === y);
}

function locate(lon: number, lat: number, z: number) {
  const world = 2 ** z;
  const sin = Math.sin((lat * Math.PI) / 180);
  const mx = ((lon + 180) / 360) * world;
  const my = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * world;
  const x = Math.floor(mx);
  const y = Math.floor(my);
  return { x, y, px: (mx - x) * EXTENT, py: (my - y) * EXTENT };
}

/** Whether the deepest stored tile at a place covers it. */
function covered(lon: number, lat: number): boolean {
  for (let z = 10; z >= 7; z--) {
    const { x, y, px, py } = locate(lon, lat, z);
    const tile = find(z, x, y);
    if (tile === undefined) continue;
    const mask = maskFromTile(tile.bytes);
    if (mask.kind !== 'mixed') return mask.kind === 'outside';
    return new MaskIndex(mask.rings, MASK_BOX).contains(px, py);
  }
  return true;
}

/** About 20 m of latitude. */
const NEAR = 0.00018;

describe('the mask pyramid', () => {
  it('leaves out tiles at the first zoom that are wholly outside', () => {
    const { x, y } = locate(-110, 40.5, 7);
    expect(find(7, x, y)).toBeUndefined();
    expect(tiles.every((tile) => tile.z >= 7 && tile.z <= 10)).toBe(true);
    expect(new Set(tiles.map((t) => `${String(t.z)}/${String(t.x)}/${String(t.y)}`)).size).toBe(
      tiles.length,
    );
  });

  it('uncovers a point just inside the border and covers one just outside', () => {
    for (const lon of [-99.93, -99.5, -98.21, -97.07]) {
      expect(covered(lon, NORTH - NEAR), `inside at ${String(lon)}`).toBe(false);
      expect(covered(lon, NORTH + NEAR), `outside at ${String(lon)}`).toBe(true);
    }
    expect(covered(-99.5, 40.5)).toBe(false);
    expect(covered(-101, 40.5)).toBe(true);
  });

  it('goes deepest along the border, and less deep at sea', () => {
    const border = locate(-99.5, NORTH, 10);
    expect(
      decodeTile(find(10, border.x, border.y)?.bytes ?? new Uint8Array()).map((l) => l.name),
    ).toEqual([MASK_LAYER, BORDER_LAYER]);
    // The south coast stops at zoom 8.
    const coast = locate(-99.5, SOUTH, 8);
    expect(find(8, coast.x, coast.y)).toBeDefined();
    const deeper = locate(-99.5, SOUTH, 9);
    expect(find(9, deeper.x, deeper.y)).toBeUndefined();
  });

  it('stores tiles wholly inside or outside as one of two small tiles', () => {
    const kinds = new Map<Uint8Array, number>();
    for (const tile of tiles) kinds.set(tile.bytes, (kinds.get(tile.bytes) ?? 0) + 1);
    expect(kinds.get(INSIDE_TILE) ?? 0).toBeGreaterThan(0);
    expect(kinds.get(OUTSIDE_TILE) ?? 0).toBeGreaterThan(0);
    expect(INSIDE_TILE.length + OUTSIDE_TILE.length).toBeLessThan(64);
    expect(maskFromTile(INSIDE_TILE).kind).toBe('inside');
    expect(maskFromTile(OUTSIDE_TILE).kind).toBe('outside');
  });

  it('draws the border line along the edge of the mask, and nowhere at sea', () => {
    const { x, y } = locate(-99.5, NORTH, 10);
    const mask = maskFromTile(find(10, x, y)?.bytes ?? new Uint8Array());
    expect(mask.kind).toBe('mixed');
    expect(mask.border.length).toBeGreaterThan(0);
    const index = new MaskIndex(mask.rings, MASK_BOX);
    for (const line of mask.border) {
      for (let i = 0; i + 1 < line.length; i += 2) {
        const px = line[i] ?? 0;
        const py = line[i + 1] ?? 0;
        if (px <= 0 || px >= EXTENT) continue;
        // On the edge: masked a unit to the north, not a unit to the south.
        expect(index.contains(px, py - 1)).toBe(true);
        expect(index.contains(px, py + 1)).toBe(false);
      }
    }
    const coast = locate(-99.5, SOUTH, 8);
    expect(maskFromTile(find(8, coast.x, coast.y)?.bytes ?? new Uint8Array()).border).toEqual([]);
  });
});

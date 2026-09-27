// @vitest-environment node
/**
 * Clipping to a tile, and MaskIndex: which points are masked, and where lines
 * are cut, against a mask shaped like a stretch of border.
 */
import { describe, expect, it } from 'vitest';

import { MASK_BOX } from '../format';
import { MaskIndex, boxRing, clipLine, clipRing, reverseRing, ringArea } from '../geometry';

const BOX = { lo: 0, hi: 100 };

describe('clipping', () => {
  it('clips a ring to the box, keeping its orientation and the area inside', () => {
    const ring = [-50, -50, 50, -50, 50, 50, -50, 50];
    const clipped = clipRing(ring, BOX);
    expect(ringArea(clipped)).toBeCloseTo(2500);
    expect(Math.sign(ringArea(clipRing(reverseRing(ring), BOX)))).toBe(-1);
    expect(clipRing([200, 200, 300, 200, 300, 300], BOX)).toEqual([]);
  });

  it('cuts a line to the parts inside the box', () => {
    expect(clipLine([-10, 50, 110, 50], BOX)).toEqual([[0, 50, 100, 50]]);
    expect(clipLine([10, 10, 20, 20, 30, 30], BOX)).toEqual([[10, 10, 20, 20, 30, 30]]);
    // Out and back in: two parts.
    expect(clipLine([50, 50, 150, 50, 150, 60, 50, 60], BOX)).toEqual([
      [50, 50, 100, 50],
      [100, 60, 50, 60],
    ]);
    expect(clipLine([200, 0, 300, 0], BOX)).toEqual([]);
  });
});

/**
 * A mask over the box's northern part: everything north of a zigzag border
 * from west to east is outside the US, and a US island sits in it.
 */
const BORDER = [-128, 2000, 1000, 1800, 2000, 2200, 3000, 1900, 4224, 2100];
const NORTH = [...BORDER, 4224, -128, -128, -128];
const ISLAND = reverseRing([1000, 500, 1400, 500, 1400, 900, 1000, 900]);
/** Where the border crosses x = 1200: between (1000, 1800) and (2000, 2200). */
const BORDER_AT_1200 = 1800 + (200 / 1000) * 400;

function mask(): MaskIndex {
  // The part north of the border, clockwise on screen, and the island a hole in it.
  const ring = ringArea(NORTH) > 0 ? NORTH : reverseRing(NORTH);
  return new MaskIndex([ring, ISLAND], MASK_BOX, 64);
}

describe('MaskIndex', () => {
  it('masks points north of the border and leaves the rest', () => {
    const index = mask();
    expect(index.empty).toBe(false);
    expect(index.full).toBe(false);
    expect(index.contains(500, 100)).toBe(true);
    expect(index.contains(500, 3000)).toBe(false);
    // Either side of the border, close to it.
    expect(index.contains(1000, 1799)).toBe(true);
    expect(index.contains(1000, 1801)).toBe(false);
    expect(index.contains(2000, 2199)).toBe(true);
    expect(index.contains(2000, 2201)).toBe(false);
    // The island is not masked; the water around it is.
    expect(index.contains(1200, 700)).toBe(false);
    expect(index.contains(1200, 450)).toBe(true);
    // Past the box nothing is masked.
    expect(index.contains(-1000, 100)).toBe(false);
  });

  it('answers for whole rectangles quickly and conservatively', () => {
    const index = mask();
    expect(index.covers(200, 200, 400, 400)).toBe(true);
    expect(index.covers(200, 200, 400, 3000)).toBe(false);
    expect(index.clear(200, 3000, 400, 3500)).toBe(true);
    expect(index.clear(200, 200, 400, 3000)).toBe(false);
    // Wholly past the box: clear.
    expect(index.clear(-9000, -9000, -8000, -8000)).toBe(true);
  });

  it('cuts a road where it crosses the border, keeping the US part', () => {
    const index = mask();
    const parts = index.unmaskedParts([1000, 3000, 1000, 1000]);
    expect(parts).toHaveLength(1);
    const [part] = parts;
    expect(part?.[0]).toBe(1000);
    expect(part?.[1]).toBe(3000);
    expect(part?.[3]).toBeCloseTo(1800, 6);
    // A road wholly north of it is gone; one wholly south is whole.
    expect(index.unmaskedParts([100, 100, 800, 300])).toEqual([]);
    expect(index.unmaskedParts([100, 3000, 800, 3300, 900, 3900])).toEqual([
      [100, 3000, 800, 3300, 900, 3900],
    ]);
  });

  it('keeps each US stretch of a road that goes in and out', () => {
    const index = mask();
    // Across the island: south of the border, over water, the island, water, back.
    const parts = index.unmaskedParts([1200, 3000, 1200, 700, 1200, 300]);
    expect(parts).toHaveLength(2);
    expect(parts[0]?.[3]).toBeCloseTo(BORDER_AT_1200, 6);
    // The island's stretch, joined across the road's bend at 700.
    expect(parts[1]).toHaveLength(6);
    expect(parts[1]?.[1]).toBeCloseTo(900, 6);
    expect(parts[1]?.[3]).toBe(700);
    expect(parts[1]?.[5]).toBeCloseTo(500, 6);
  });

  it('knows an empty mask and a full one', () => {
    const empty = new MaskIndex([], MASK_BOX);
    expect(empty.empty).toBe(true);
    expect(empty.contains(10, 10)).toBe(false);
    expect(empty.unmaskedParts([0, 0, 10, 10])).toEqual([[0, 0, 10, 10]]);
    const full = new MaskIndex([boxRing(MASK_BOX)], MASK_BOX);
    expect(full.full).toBe(true);
    expect(full.contains(10, 10)).toBe(true);
    expect(full.unmaskedParts([0, 0, 10, 10])).toEqual([]);
  });
});

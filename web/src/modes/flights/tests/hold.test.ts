/**
 * The map's labels and Flights' tags giving way to each other (hold.ts): a label is turned down
 * where a held tag sits, every label placed is noted for the calm tags, and with nothing held a
 * label is placed as MapLibre placed it.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { describe, expect, it, vi } from 'vitest';

import { CONTROL_CLEARANCE } from '../../../map/basemap/clearance';
import { HOLD_CLEARANCE, holdLabels } from '../hold';

/** The band MapLibre's collision grid keeps around the screen, in CSS pixels. */
const BAND = 100;

/** A stand-in for MapLibre's collision index: it places whatever it is asked to. */
class FakeIndex {
  readonly transform = { width: 400 };
  readonly screenRightBoundary = 400 + BAND;

  placeCollisionBox(box: number[]): { box: number[]; placeable: boolean; offscreen: boolean } {
    return { box, placeable: true, offscreen: false };
  }

  placeCollisionCircles(circles: number[]): {
    circles: number[];
    offscreen: boolean;
    collisionDetected: boolean;
  } {
    return { circles, offscreen: false, collisionDetected: false };
  }
}

const inGrid = (x0: number, y0: number, x1: number, y1: number): number[] => [
  x0 + BAND,
  y0 + BAND,
  x1 + BAND,
  y1 + BAND,
];

function fakeMap(): { map: MapLibreMap; repaints: () => number } {
  const repaint = vi.fn();
  const map = {
    on: vi.fn(),
    off: vi.fn(),
    triggerRepaint: repaint,
    style: { placement: { collisionIndex: new FakeIndex() } },
  } as unknown as MapLibreMap;
  return { map, repaints: () => repaint.mock.calls.length };
}

describe('the labels and the held tags', () => {
  it('keeps the same clear space around a tag as around a control', () => {
    expect(HOLD_CLEARANCE).toBe(CONTROL_CLEARANCE);
  });

  it('turns down a label where a held tag sits, and notes every label placed', () => {
    const { map, repaints } = fakeMap();
    let tags = [{ x0: 150, y0: 100, x1: 190, y1: 116 }];
    const hold = holdLabels(map, () => tags);
    // The first placing went without the tags: the map places its labels again.
    expect(repaints()).toBe(1);
    // Each placing reads the boxes afresh, on an index of its own.
    let index = new FakeIndex();
    const place = (box: number[]): boolean => index.placeCollisionBox(box).placeable;
    expect(place(inGrid(160, 104, 220, 114))).toBe(false);
    expect(place(inGrid(150, 116 + CONTROL_CLEARANCE + 1, 190, 130))).toBe(true);
    expect(place(inGrid(10, 10, 60, 24))).toBe(true);
    // The two placed, on the map's canvas; the one held off is not among them.
    expect(hold.placed()).toEqual([
      { x0: 150, y0: 116 + CONTROL_CLEARANCE + 1, x1: 190, y1: 130 },
      { x0: 10, y0: 10, x1: 60, y1: 24 },
    ]);
    // A street's name, as circles along its run: one under the tag turns it down.
    const circles = (points: [number, number][]): boolean =>
      index.placeCollisionCircles(points.flatMap(([x, y]) => [x + BAND, y + BAND, 5, 0]))
        .collisionDetected;
    expect(
      circles([
        [50, 200],
        [70, 200],
      ]),
    ).toBe(false);
    expect(
      circles([
        [50, 200],
        [170, 108],
      ]),
    ).toBe(true);
    // The tag moves: the next placing places the name again, and holds the new spot.
    tags = [{ x0: 20, y0: 20, x1: 60, y1: 36 }];
    index = new FakeIndex();
    expect(place(inGrid(160, 104, 220, 114))).toBe(true);
    expect(place(inGrid(30, 25, 50, 30))).toBe(false);
    expect(hold.placed()).toEqual([{ x0: 160, y0: 104, x1: 220, y1: 114 }]);
    hold.release();
  });

  it('places every label as MapLibre does once the tags are let go', () => {
    const { map, repaints } = fakeMap();
    const hold = holdLabels(map, () => [{ x0: 0, y0: 0, x1: 400, y1: 300 }]);
    hold.release();
    // Let go: the names come back at the next placing.
    expect(repaints()).toBe(2);
    const index = new FakeIndex();
    expect(index.placeCollisionBox(inGrid(30, 25, 50, 30)).placeable).toBe(true);
    expect(hold.placed()).toEqual([]);
  });
});

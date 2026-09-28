/**
 * Labels kept whole (clearance.ts): MapLibre's two placing checks, wrapped,
 * turn down a label that would reach under one of the page's controls or
 * past the screen's edge, and leave every other label as MapLibre placed it.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CONTROL_CLEARANCE, keepLabelsClear, reaches, wrapCollisionIndex } from '../clearance';
import type { LabelClearance } from '../clearance';

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

function rect(x: number, y: number, width: number, height: number): DOMRect {
  return {
    x,
    y,
    left: x,
    top: y,
    width,
    height,
    right: x + width,
    bottom: y + height,
    toJSON: () => ({}),
  };
}

function element(box: DOMRect): Element {
  const node = document.createElement('div');
  node.getBoundingClientRect = () => box;
  return node;
}

/** A map whose canvas is 400 by 300 at the page's corner, having placed its labels once. */
function fakeMap(index: FakeIndex): { map: MapLibreMap; repaints: () => number } {
  const canvas = element(rect(0, 0, 400, 300));
  const repaint = vi.fn();
  const map = {
    getCanvas: () => canvas,
    on: vi.fn(),
    off: vi.fn(),
    triggerRepaint: repaint,
    style: { placement: { collisionIndex: index } },
  } as unknown as MapLibreMap;
  return { map, repaints: () => repaint.mock.calls.length };
}

/** A box as MapLibre's index reports it: screen pixels, offset by the band. */
const inGrid = (x0: number, y0: number, x1: number, y1: number): number[] => [
  x0 + BAND,
  y0 + BAND,
  x1 + BAND,
  y1 + BAND,
];

let kept: LabelClearance | null = null;
afterEach(() => {
  kept?.destroy();
  kept = null;
});

describe('reaches', () => {
  it('says whether a box runs into any of the boxes', () => {
    const boxes = [{ x0: 10, y0: 10, x1: 20, y1: 20 }];
    expect(reaches(boxes, 0, 0, 10, 10)).toBe(false);
    expect(reaches(boxes, 0, 0, 11, 11)).toBe(true);
    expect(reaches(boxes, 12, 12, 14, 14)).toBe(true);
    expect(reaches(boxes, 21, 0, 30, 30)).toBe(false);
    expect(reaches([], 0, 0, 100, 100)).toBe(false);
  });
});

describe('keepLabelsClear', () => {
  it("turns down a label under a control or past the screen's edge, and no other", async () => {
    const index = new FakeIndex();
    const { map, repaints } = fakeMap(index);
    const field = element(rect(100, 20, 200, 44));
    const hidden = element(rect(0, 0, 0, 0));
    kept = keepLabelsClear(map, () => [field, hidden]);
    expect(await kept.ready).toBe(true);
    // The first placing went without the controls: the map places its labels again.
    expect(repaints()).toBe(1);
    const place = (box: number[]): boolean => index.placeCollisionBox(box).placeable;
    // Clear of the field, by more than the clearance: placed as MapLibre placed it.
    expect(place(inGrid(20, 100, 90, 112))).toBe(true);
    expect(place(inGrid(100, 64 + CONTROL_CLEARANCE + 1, 200, 80))).toBe(true);
    // Under the field, or within the clearance of it: turned down, whole.
    expect(place(inGrid(250, 50, 330, 62))).toBe(false);
    expect(place(inGrid(100, 64 + CONTROL_CLEARANCE - 1, 200, 80))).toBe(false);
    // Past the screen's edges: cut there, so turned down too.
    expect(place(inGrid(-10, 150, 40, 162))).toBe(false);
    expect(place(inGrid(380, 150, 410, 162))).toBe(false);
    expect(place(inGrid(150, 295, 220, 310))).toBe(false);
    // A street's name, as circles along its run: one under the field turns the name down.
    const circles = (points: [number, number][]): boolean =>
      index.placeCollisionCircles(points.flatMap(([x, y]) => [x + BAND, y + BAND, 5, 0]))
        .collisionDetected;
    expect(
      circles([
        [50, 150],
        [70, 150],
        [90, 150],
      ]),
    ).toBe(false);
    expect(
      circles([
        [50, 150],
        [150, 60],
        [90, 150],
      ]),
    ).toBe(true);
  });

  it('keeps nothing clear once it is let go', async () => {
    const index = new FakeIndex();
    const { map } = fakeMap(index);
    kept = keepLabelsClear(map, () => [element(rect(100, 20, 200, 44))]);
    await kept.ready;
    kept.destroy();
    kept = null;
    expect(index.placeCollisionBox(inGrid(250, 50, 330, 62)).placeable).toBe(true);
  });

  it('leaves labels as MapLibre places them where its index is not the one it knows', async () => {
    expect(wrapCollisionIndex({})).toBe(false);
    const { map } = fakeMap({} as FakeIndex);
    kept = keepLabelsClear(map, () => []);
    expect(await kept.ready).toBe(false);
  });
});

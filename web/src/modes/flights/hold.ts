/**
 * The map's labels and Flights' code tags, giving way to each other (D1, LR-F12): the map keeps
 * every name it draws for Schools; a name gives way where the tag of an airport in trouble (or
 * the open one) sits, and a calm tag gives way to the names the map placed.
 *
 * The tags are drawn on a 2D canvas over the map's (layer.ts), which MapLibre's placing knows
 * nothing of. As the basemap keeps its labels clear of the page's controls (clearance.ts), so
 * here: MapLibre places every label through two methods of its collision index, and these wrap
 * them once more, on top of the basemap's own wrap, in Flights' own code. While Flights holds
 * boxes, a label that would reach into one is not placed, whole, and every label placed is
 * noted, so the calm tags can keep clear of it. With nothing held, a label is placed as before.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { ScreenBox } from '../../map/basemap/clearance';

/**
 * Clear space kept between a label and a held tag, in CSS pixels, beyond the label's own
 * padding: clearance.ts's CONTROL_CLEARANCE, held here as a type-free copy so this chunk loads
 * none of the basemap's code of its own (the page's first script stays as it is).
 */
export const HOLD_CLEARANCE = 4;

/** Whether a box from x0, y0 to x1, y1 reaches into any of `boxes` (as clearance.ts's reaches). */
function reaches(
  boxes: readonly ScreenBox[],
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): boolean {
  for (const box of boxes)
    if (x0 < box.x1 && x1 > box.x0 && y0 < box.y1 && y1 > box.y0) return true;
  return false;
}

/** The collision index as read here, in CSS pixels offset by the band it keeps around the screen. */
interface IndexLike {
  readonly transform: { readonly width: number };
  readonly screenRightBoundary: number;
  placeCollisionBox(
    this: IndexLike,
    ...args: unknown[]
  ): {
    readonly box: readonly number[];
    readonly placeable: boolean;
    readonly offscreen: boolean | null;
  };
  placeCollisionCircles(
    this: IndexLike,
    ...args: unknown[]
  ): {
    readonly circles: readonly number[];
    readonly offscreen: boolean;
    readonly collisionDetected: boolean;
  };
}

/** What gives the boxes held now, on the map's canvas: one map's tags at a time. */
let held: (() => readonly ScreenBox[]) | null = null;
/** The held boxes of each placing, in the index's own units: read once for each. */
const heldOf = new WeakMap<object, readonly ScreenBox[]>();
/** The placing the labels below were placed in, and each label's box, on the map's canvas. */
let placedIndex: object | null = null;
let placed: ScreenBox[] = [];
/** The index classes already wrapped. */
const wrapped = new WeakSet<object>();

/** How far the index's units are from the canvas's: the band around the screen. */
function shiftOf(index: IndexLike): number {
  const band = index.screenRightBoundary - index.transform.width;
  return Number.isFinite(band) ? band : 0;
}

function heldFor(index: IndexLike): readonly ScreenBox[] {
  let boxes = heldOf.get(index);
  if (boxes === undefined) {
    const shift = shiftOf(index);
    boxes = (held?.() ?? []).map((box) => ({
      x0: box.x0 + shift - HOLD_CLEARANCE,
      y0: box.y0 + shift - HOLD_CLEARANCE,
      x1: box.x1 + shift + HOLD_CLEARANCE,
      y1: box.y1 + shift + HOLD_CLEARANCE,
    }));
    heldOf.set(index, boxes);
  }
  return boxes;
}

/** Notes a label the placing `index` placed, on the map's canvas. */
function note(index: IndexLike, x0: number, y0: number, x1: number, y1: number): void {
  if (index !== placedIndex) {
    placedIndex = index;
    placed = [];
  }
  const shift = shiftOf(index);
  placed.push({ x0: x0 - shift, y0: y0 - shift, x1: x1 - shift, y1: y1 - shift });
}

/** Wraps the index class's two placing methods, once. False when they are not there to wrap. */
export function wrapPlacing(prototype: object): boolean {
  if (wrapped.has(prototype)) return true;
  const index = prototype as IndexLike;
  const methods = prototype as Record<string, unknown>;
  const placeBox = methods.placeCollisionBox;
  const placeCircles = methods.placeCollisionCircles;
  if (typeof placeBox !== 'function' || typeof placeCircles !== 'function') return false;
  const box = placeBox as IndexLike['placeCollisionBox'];
  const circles = placeCircles as IndexLike['placeCollisionCircles'];
  index.placeCollisionBox = function placeCollisionBox(this: IndexLike, ...args) {
    const result = box.apply(this, args);
    if (!result.placeable || held === null) return result;
    const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = result.box;
    if (reaches(heldFor(this), x0, y0, x1, y1))
      return { ...result, placeable: false, offscreen: false };
    note(this, x0, y0, x1, y1);
    return result;
  };
  index.placeCollisionCircles = function placeCollisionCircles(this: IndexLike, ...args) {
    const result = circles.apply(this, args);
    if (result.collisionDetected || result.circles.length === 0 || held === null) return result;
    const boxes = heldFor(this);
    const all = result.circles;
    for (let i = 0; i + 2 < all.length; i += 4) {
      const x = all[i] ?? 0;
      const y = all[i + 1] ?? 0;
      const r = all[i + 2] ?? 0;
      if (reaches(boxes, x - r, y - r, x + r, y + r))
        return { circles: [], offscreen: false, collisionDetected: true };
    }
    for (let i = 0; i + 2 < all.length; i += 4) {
      const x = all[i] ?? 0;
      const y = all[i + 1] ?? 0;
      const r = all[i + 2] ?? 0;
      note(this, x - r, y - r, x + r, y + r);
    }
    return result;
  };
  wrapped.add(prototype);
  return true;
}

/** The map's labels and a layer's marks over it, giving way to each other. */
export interface LabelHold {
  /** The box of every label the map's latest placing placed, its padding in, on the canvas. */
  placed(): readonly ScreenBox[];
  /** Lets the boxes go: the labels they held off are placed again. */
  release(): void;
}

/**
 * Keeps `map`'s labels clear of the boxes `boxes()` gives (HOLD_CLEARANCE clear, as of the
 * page's controls), read afresh for each placing, and notes the labels each placing places.
 */
export function holdLabels(map: MapLibreMap, boxes: () => readonly ScreenBox[]): LabelHold {
  held = boxes;
  placedIndex = null;
  placed = [];
  /** Once MapLibre has placed labels, its index is there to wrap. */
  const onRender = (): void => {
    const { style } = map as unknown as {
      style?: { placement?: { collisionIndex?: object } | null } | null;
    };
    const index = style?.placement?.collisionIndex;
    if (index === undefined) return;
    map.off('render', onRender);
    // The first placing went without the boxes: place the labels again with them.
    if (wrapPlacing(Object.getPrototypeOf(index) as object)) map.triggerRepaint();
  };
  map.on('render', onRender);
  onRender();
  return {
    placed: () => placed,
    release() {
      map.off('render', onRender);
      if (held === boxes) {
        held = null;
        placedIndex = null;
        placed = [];
      }
      map.triggerRepaint();
    },
  };
}

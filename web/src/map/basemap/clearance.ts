/**
 * Map labels kept whole: clear of the page's own controls and inside the
 * screen.
 *
 * MapLibre places each label where it collides with no label placed before
 * it, but it knows nothing of the page drawn over its canvas: a name that
 * runs under the search field or the legend is drawn all the same, cut off
 * by the field or printed through the legend, and a name that runs off the
 * screen is drawn cut off at its edge. Here the controls and the screen's
 * edges take part in the placing, as labels placed before all others: a
 * label whose box (or, for a street's name, one of the circles along its
 * run) would reach within CONTROL_CLEARANCE of a control, or of the screen's
 * edge, is not placed, whole, and a school's name tries its other sides of
 * the dot first. MapLibre places every label afresh each frame the view
 * changes (the style fades nothing in), and the controls' boxes are read once
 * for each placing, so names go and come whole as the map moves under the
 * controls and past the edges.
 *
 * MapLibre has no setting for this. It places every label through two
 * methods of its collision index, placeCollisionBox and
 * placeCollisionCircles; keepLabelsClear wraps those two on the index's class
 * once the map has placed its first labels, and says whether it could. With
 * a MapLibre whose index has changed, labels are placed as MapLibre alone
 * would place them, and the end-to-end tests that look for labels under the
 * controls fail (e2e/real-data.spec.ts).
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

/** Clear space kept between a label and a control, in CSS pixels, beyond the label's own padding. */
export const CONTROL_CLEARANCE = 4;

/** A box on the map's canvas, in CSS pixels from its top left corner. */
export interface ScreenBox {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

/** What MapLibre's placeCollisionBox returns, as far as it is read here. */
interface PlacedBox {
  readonly box: readonly number[];
  readonly placeable: boolean;
  readonly offscreen: boolean | null;
}

/** What its placeCollisionCircles returns: x, y, radius and a flag for each circle, in turn. */
interface PlacedCircles {
  readonly circles: readonly number[];
  readonly offscreen: boolean;
  readonly collisionDetected: boolean;
}

/**
 * The collision index as read here. Its boxes are in CSS pixels, offset by
 * the band it keeps around the screen: screenRightBoundary is the screen's
 * width plus that band.
 */
interface CollisionIndexLike {
  readonly transform: { readonly width: number };
  readonly screenRightBoundary: number;
  placeCollisionBox(this: CollisionIndexLike, ...args: unknown[]): PlacedBox;
  placeCollisionCircles(this: CollisionIndexLike, ...args: unknown[]): PlacedCircles;
}

/**
 * The boxes labels keep clear of, for the map that is keeping them clear:
 * one map at a time, the page's.
 */
let keepOut: (() => readonly ScreenBox[]) | null = null;

/** The boxes of each placing, in the index's own units: read once for each. */
const boxesOf = new WeakMap<object, readonly ScreenBox[]>();

/** The index classes already wrapped. */
const wrapped = new WeakSet<object>();

function boxesFor(index: CollisionIndexLike): readonly ScreenBox[] {
  let boxes = boxesOf.get(index);
  if (boxes === undefined) {
    const band = index.screenRightBoundary - index.transform.width;
    const shift = Number.isFinite(band) ? band : 0;
    boxes = (keepOut?.() ?? []).map((box) => ({
      x0: box.x0 + shift - CONTROL_CLEARANCE,
      y0: box.y0 + shift - CONTROL_CLEARANCE,
      x1: box.x1 + shift + CONTROL_CLEARANCE,
      y1: box.y1 + shift + CONTROL_CLEARANCE,
    }));
    boxesOf.set(index, boxes);
  }
  return boxes;
}

/** Whether a box from x0, y0 to x1, y1 reaches into any of `boxes`. */
export function reaches(
  boxes: readonly ScreenBox[],
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): boolean {
  for (const box of boxes) {
    if (x0 < box.x1 && x1 > box.x0 && y0 < box.y1 && y1 > box.y0) return true;
  }
  return false;
}

/** Wraps the index class's two placing methods, once. False when they are not there to wrap. */
export function wrapCollisionIndex(prototype: object): boolean {
  if (wrapped.has(prototype)) return true;
  const index = prototype as CollisionIndexLike;
  const methods = prototype as Record<string, unknown>;
  const placeBox = methods.placeCollisionBox;
  const placeCircles = methods.placeCollisionCircles;
  if (typeof placeBox !== 'function' || typeof placeCircles !== 'function') return false;
  const box = placeBox as CollisionIndexLike['placeCollisionBox'];
  const circles = placeCircles as CollisionIndexLike['placeCollisionCircles'];
  index.placeCollisionBox = function placeCollisionBox(this: CollisionIndexLike, ...args) {
    const placed = box.apply(this, args);
    if (!placed.placeable || keepOut === null) return placed;
    const [x0 = 0, y0 = 0, x1 = 0, y1 = 0] = placed.box;
    return reaches(boxesFor(this), x0, y0, x1, y1)
      ? { ...placed, placeable: false, offscreen: false }
      : placed;
  };
  index.placeCollisionCircles = function placeCollisionCircles(this: CollisionIndexLike, ...args) {
    const placed = circles.apply(this, args);
    if (placed.collisionDetected || placed.circles.length === 0 || keepOut === null) return placed;
    const boxes = boxesFor(this);
    if (boxes.length === 0) return placed;
    const all = placed.circles;
    for (let i = 0; i + 2 < all.length; i += 4) {
      const x = all[i] ?? 0;
      const y = all[i + 1] ?? 0;
      const r = all[i + 2] ?? 0;
      if (reaches(boxes, x - r, y - r, x + r, y + r)) {
        return { circles: [], offscreen: false, collisionDetected: true };
      }
    }
    return placed;
  };
  wrapped.add(prototype);
  return true;
}

/** Keeps the map's labels clear of the page's controls. */
export interface LabelClearance {
  /** Resolves once labels keep clear, true, or false where this MapLibre cannot be made to. */
  readonly ready: Promise<boolean>;
  /**
   * The boxes labels keep CONTROL_CLEARANCE clear of now, on the map's
   * canvas: the controls shown and bands just outside the screen's edges.
   */
  boxes(): readonly ScreenBox[];
  destroy(): void;
}

/** How far past the screen's edges the bands labels keep out of reach, in CSS pixels: past any label. */
const OFF_SCREEN = 10_000;

/**
 * Keeps `map`'s labels inside its screen and clear of the boxes of
 * `controls()`, the page's controls over it, read afresh for each placing. A
 * control with no box (one not shown) keeps nothing clear. The map is placed
 * again whenever a control changes size, or appears.
 */
export function keepLabelsClear(
  map: MapLibreMap,
  controls: () => Iterable<Element>,
): LabelClearance {
  // The canvas itself: its container has no height of its own.
  const canvas = map.getCanvas();
  /** Each control watched, and its size when last seen: a change places the labels again. */
  const watched = new Map<Element, string>();
  const resized =
    typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver((entries) => {
          let changed = false;
          for (const { target, contentRect } of entries) {
            const size = `${String(contentRect.width)}x${String(contentRect.height)}`;
            const seen = watched.get(target);
            watched.set(target, size);
            // The first sight of a control is its size when the map first read it: no change.
            if (seen !== undefined && seen !== '' && seen !== size) changed = true;
          }
          if (changed) map.triggerRepaint();
        });
  const boxes = (): readonly ScreenBox[] => {
    const origin = canvas.getBoundingClientRect();
    const { width, height } = origin;
    // The screen's four edges, as bands just outside it.
    const found: ScreenBox[] = [
      { x0: -OFF_SCREEN, y0: -OFF_SCREEN, x1: 0, y1: height + OFF_SCREEN },
      { x0: width, y0: -OFF_SCREEN, x1: width + OFF_SCREEN, y1: height + OFF_SCREEN },
      { x0: -OFF_SCREEN, y0: -OFF_SCREEN, x1: width + OFF_SCREEN, y1: 0 },
      { x0: -OFF_SCREEN, y0: height, x1: width + OFF_SCREEN, y1: height + OFF_SCREEN },
    ];
    for (const control of controls()) {
      if (!watched.has(control)) {
        watched.set(control, '');
        resized?.observe(control);
      }
      const rect = control.getBoundingClientRect();
      if (!(rect.width > 0 && rect.height > 0)) continue;
      found.push({
        x0: rect.left - origin.left,
        y0: rect.top - origin.top,
        x1: rect.right - origin.left,
        y1: rect.bottom - origin.top,
      });
    }
    return found;
  };
  keepOut = boxes;
  let settle: (kept: boolean) => void = () => undefined;
  const ready = new Promise<boolean>((resolve) => {
    settle = resolve;
  });
  /** Once MapLibre has placed labels, its index is there to wrap. */
  const onRender = (): void => {
    const { style } = map as unknown as {
      style?: { placement?: { collisionIndex?: object } | null } | null;
    };
    const index = style?.placement?.collisionIndex;
    if (index === undefined) return;
    map.off('render', onRender);
    const kept = wrapCollisionIndex(Object.getPrototypeOf(index) as object);
    // The first placing went without the controls: place the labels again with them.
    if (kept) map.triggerRepaint();
    settle(kept);
  };
  map.on('render', onRender);
  onRender();
  return {
    ready,
    boxes,
    destroy() {
      map.off('render', onRender);
      resized?.disconnect();
      watched.clear();
      if (keepOut === boxes) keepOut = null;
      settle(false);
    },
  };
}

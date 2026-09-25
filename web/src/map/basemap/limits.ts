/**
 * How far the map zooms out and pans on a given screen.
 *
 * The national view fits the continental US into the frame, the box the
 * inline still is drawn in. From there:
 *
 * - Zooming out stops ZOOM_SLACK levels below that fit, so the country is
 *   never much smaller than at the national view.
 * - The screen stays inside the national view grown by VIEW_MARGIN. At the
 *   widest zoom that leaves a few percent of play either way, so the whole
 *   country stays on screen; zoomed in, it lets the view reach every edge.
 * - Zoomed in, part of the country stays on screen: the middle half of the
 *   screen, across and down, always takes in some US land, as mapped band by
 *   band from the outline (us-reach.ts). A coast or border can be panned to,
 *   not past the middle of a half screen, so the view never drifts out over
 *   open ocean or into Canada or Mexico. Lakes and bays up to two degrees
 *   wide count as land, so they can be panned across at any zoom.
 * - Every school in the directory is inside that land map, the few on islands
 *   the outline leaves out (such as Monhegan, off Maine) too, so the map can
 *   center on any school at street zoom and pan around it.
 * - The center stays inside CENTER_BOUNDS, which view links share (bounds.ts).
 *
 * The national view itself is always allowed, so nothing moves on load or
 * when the map takes over from the inline still. Everything here is plain
 * math on Web Mercator world units (0..1, y growing southward, as MapLibre
 * uses), so the map, links and tests share one implementation.
 */
import {
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
} from '../glow/mercator';
import { CENTER_BOUNDS, MAX_ZOOM, MIN_ZOOM } from './bounds';
import type { MapView } from './bounds';
import { US_BOUNDS } from './us-geo';
import { US_LAND } from './us-reach';

/** Zoom levels the map zooms out past the national view, at most. */
export const ZOOM_SLACK = 0.3;

/**
 * How much larger than the screen at the widest zoom the area it pans in is,
 * as a share of the screen: 0.1 leaves 5% of play on each side.
 */
export const VIEW_MARGIN = 0.1;

/**
 * Share of a half screen, across and down, that a coast or border can move
 * past the center: 0.5 keeps some of the US inside the middle half of the screen.
 */
export const LEASH = 0.5;

/** MapLibre's tiles are 512 px: the world is 512 * 2^zoom px wide. */
const TILE_SIZE = 512;

/** MapLibre refuses a minimum zoom below this. */
const MAPLIBRE_MIN_ZOOM = -2;

/** World units a position can sit past a limit and still count as inside: far below a pixel at zoom 16. */
const EPSILON = 1e-12;

/**
 * Degrees the center can always stray from the land map (us-reach.ts), at
 * least. The map comes from the outline drawn at the national view, whose
 * shores can sit a few kilometers inside the real ones; this keeps every real
 * shore reachable at street zoom, where the leash is shorter than that.
 */
const SHORE_SLACK = 0.04;

/** A screen size in CSS pixels. */
export interface Size {
  readonly width: number;
  readonly height: number;
}

/** Distances from each edge of the screen to the frame the national view fits into, in CSS pixels. */
export interface Insets {
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
  readonly left: number;
}

/** A rectangle in Web Mercator world units. */
export interface Box {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

/** The limits for one screen. Recompute them whenever the screen or the frame changes size. */
export interface ViewLimits {
  /** The screen, in CSS pixels. */
  readonly width: number;
  readonly height: number;
  /** The national view: the continental US fitted into the frame. */
  readonly fit: MapView;
  /** The widest zoom: ZOOM_SLACK below the national view. */
  readonly minZoom: number;
  readonly maxZoom: number;
  /** The rectangle the screen stays inside, in world units. */
  readonly area: Box;
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** Element i of a list, or NaN past its ends (the lists here are never sparse). */
function item(values: readonly number[], index: number): number {
  return values[index] ?? Number.NaN;
}

function boxOf(bounds: readonly [number, number, number, number]): Box {
  const [west, south, east, north] = bounds;
  return {
    x0: mercatorXFromLng(west),
    y0: mercatorYFromLat(north),
    x1: mercatorXFromLng(east),
    y1: mercatorYFromLat(south),
  };
}

const US_BOX = boxOf(US_BOUNDS);
const CENTER_BOX = boxOf(CENTER_BOUNDS);

/**
 * The land map as rectangles in world units, one per piece of land in each
 * band of latitude: x0, y0, x1, y1 (north-west and south-east corners) in turn.
 */
const LAND = Float64Array.from(
  US_LAND.runs.flatMap((run) => {
    const corners: number[] = [];
    for (let i = 0; i + 3 < run.length; i += 4) {
      corners.push(
        mercatorXFromLng(item(run, i)),
        mercatorYFromLat(item(run, i + 3)),
        mercatorXFromLng(item(run, i + 1)),
        mercatorYFromLat(item(run, i + 2)),
      );
    }
    return corners;
  }),
);

/** SHORE_SLACK in world units, the same across and down, as a leash is. */
const SLACK = SHORE_SLACK / 360;

/**
 * The limits for a screen of `size` whose national view fits the US inside
 * `insets`. A frame with no area falls back to the whole screen.
 */
export function viewLimits(size: Size, insets: Insets): ViewLimits {
  const width = Number.isFinite(size.width) ? Math.max(0, size.width) : 0;
  const height = Number.isFinite(size.height) ? Math.max(0, size.height) : 0;
  let innerWidth = width - insets.left - insets.right;
  let innerHeight = height - insets.top - insets.bottom;
  let offsetX = (insets.left - insets.right) / 2;
  let offsetY = (insets.top - insets.bottom) / 2;
  if (!(innerWidth > 0 && innerHeight > 0)) {
    innerWidth = width;
    innerHeight = height;
    offsetX = 0;
    offsetY = 0;
  }
  const fitScale =
    innerWidth > 0 && innerHeight > 0
      ? Math.min(innerWidth / (US_BOX.x1 - US_BOX.x0), innerHeight / (US_BOX.y1 - US_BOX.y0))
      : TILE_SIZE * 2 ** MIN_ZOOM;
  const fitZoom = clamp(Math.log2(fitScale / TILE_SIZE), MAPLIBRE_MIN_ZOOM, MAX_ZOOM);
  // The same center MapLibre's fitBounds gives: the middle of the US, moved
  // by half the difference between opposite insets.
  const scale = TILE_SIZE * 2 ** fitZoom;
  const fitX = (US_BOX.x0 + US_BOX.x1) / 2 - offsetX / scale;
  const fitY = (US_BOX.y0 + US_BOX.y1) / 2 - offsetY / scale;
  // Tiny screens fit the US below MIN_ZOOM; they keep their fit, with no slack below it.
  const minZoom = clamp(
    Math.max(fitZoom - ZOOM_SLACK, Math.min(fitZoom, MIN_ZOOM)),
    MAPLIBRE_MIN_ZOOM,
    fitZoom,
  );
  const widest = TILE_SIZE * 2 ** minZoom;
  const halfWidth = (width / 2 / widest) * (1 + VIEW_MARGIN);
  const halfHeight = (height / 2 / widest) * (1 + VIEW_MARGIN);
  return {
    width,
    height,
    fit: { lat: latFromMercatorY(fitY), lon: lngFromMercatorX(fitX), zoom: fitZoom },
    minZoom,
    maxZoom: MAX_ZOOM,
    area: {
      x0: fitX - halfWidth,
      y0: fitY - halfHeight,
      x1: fitX + halfWidth,
      y1: fitY + halfHeight,
    },
  };
}

/**
 * The allowed view nearest `view` under `limits`. A view already allowed
 * comes back exactly as given; anything else comes back at the nearest zoom
 * the limits allow and, at that zoom, the nearest allowed center.
 *
 * At one zoom the center is allowed inside any piece of land grown by the
 * leash (so the middle half of the screen takes it in), cut to the box that
 * keeps the screen in the area and the center in CENTER_BOUNDS. Being the
 * nearest point of those rectangles, a view pushed against an edge slides
 * along it and comes to rest, and never flips back and forth between two
 * places. MapLibre runs this on every change of view, so it allocates nothing
 * and reads each rectangle once.
 */
export function constrainView(limits: ViewLimits, view: MapView): MapView {
  const zoom = clamp(
    Number.isFinite(view.zoom) ? view.zoom : limits.fit.zoom,
    limits.minZoom,
    limits.maxZoom,
  );
  if (!Number.isFinite(view.lat) || !Number.isFinite(view.lon)) {
    return { lat: limits.fit.lat, lon: limits.fit.lon, zoom };
  }
  const x = mercatorXFromLng(view.lon);
  const y = mercatorYFromLat(view.lat);
  const scale = TILE_SIZE * 2 ** zoom;
  const halfWidth = limits.width / 2 / scale;
  const halfHeight = limits.height / 2 / scale;
  const leashX = Math.max(LEASH * halfWidth, SLACK);
  const leashY = Math.max(LEASH * halfHeight, SLACK);
  const { area } = limits;
  const boxX0 = Math.max(area.x0 + halfWidth, CENTER_BOX.x0);
  const boxX1 = Math.min(area.x1 - halfWidth, CENTER_BOX.x1);
  const boxY0 = Math.max(area.y0 + halfHeight, CENTER_BOX.y0);
  const boxY1 = Math.min(area.y1 - halfHeight, CENTER_BOX.y1);
  let nearest = Infinity;
  let nearestX = mercatorXFromLng(limits.fit.lon);
  let nearestY = mercatorYFromLat(limits.fit.lat);
  for (let i = 0; i < LAND.length; i += 4) {
    const x0 = Math.max((LAND[i] ?? 0) - leashX, boxX0);
    const x1 = Math.min((LAND[i + 2] ?? 0) + leashX, boxX1);
    if (x0 > x1) continue;
    const y0 = Math.max((LAND[i + 1] ?? 0) - leashY, boxY0);
    const y1 = Math.min((LAND[i + 3] ?? 0) + leashY, boxY1);
    if (y0 > y1) continue;
    const cx = x < x0 ? x0 : x > x1 ? x1 : x;
    const cy = y < y0 ? y0 : y > y1 ? y1 : y;
    const distance = (cx - x) ** 2 + (cy - y) ** 2;
    if (distance <= EPSILON ** 2) return { lat: view.lat, lon: view.lon, zoom };
    if (distance < nearest) {
      nearest = distance;
      nearestX = cx;
      nearestY = cy;
    }
  }
  // With no rectangle at all (never at a zoom the limits allow, since the
  // national view's center is over land and inside the box), it holds that center.
  // Snap into CENTER_BOUNDS in degrees, which the round trip through world units can miss by a hair.
  const [west, south, east, north] = CENTER_BOUNDS;
  return {
    lat: clamp(latFromMercatorY(nearestY), south, north),
    lon: clamp(lngFromMercatorX(nearestX), west, east),
    zoom,
  };
}

/** The screen at a view, in world units: for tests and for callers placing things on screen. */
export function screenBox(limits: Pick<ViewLimits, 'width' | 'height'>, view: MapView): Box {
  const scale = TILE_SIZE * 2 ** view.zoom;
  const x = mercatorXFromLng(view.lon);
  const y = mercatorYFromLat(view.lat);
  const halfWidth = limits.width / 2 / scale;
  const halfHeight = limits.height / 2 / scale;
  return { x0: x - halfWidth, y0: y - halfHeight, x1: x + halfWidth, y1: y + halfHeight };
}

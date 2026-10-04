/**
 * Where the map looks to show a school its detail panel has opened for: the
 * school in the middle of the map the panel leaves in view, right of the
 * panel beside the map, above the sheet on a phone (at the height the sheet
 * opens to, ui/sheet-geometry.ts), and below the search strip either way; and
 * the schools around a ZIP code, all of them in that part of the map.
 * And the part of the map in view now, which a tap on several schools zooms
 * them into.
 *
 * Loaded with the rest of the app after the first paint (app/boot.ts
 * re-exports it), so the page's first script carries none of it.
 */

import type { MapView } from '../map/basemap';
import { OPEN_SHARE } from '../ui/sheet-geometry';

/**
 * The panel's width beside the map, by the screen's width (DetailPanel.svelte):
 * wider from 1024 and 1280 pixels, so its chart is bigger and its lines wrap less.
 */
export const PANEL_WIDTHS: readonly { readonly from: number; readonly width: number }[] = [
  { from: 1280, width: 460 },
  { from: 1024, width: 420 },
  { from: 0, width: 368 },
];
/** The panel's width on the narrowest screen it sits beside the map on. */
export const PANEL_WIDTH = 368;
export const PANEL_EDGE = 20;

/** The panel's width on a screen `screenWidth` pixels wide, beside the map. */
export function panelWidth(screenWidth: number): number {
  return PANEL_WIDTHS.find((step) => screenWidth >= step.from)?.width ?? PANEL_WIDTH;
}
/** Screens narrower than this show the panel as a sheet over the foot of the map (index.html). */
export const PHONE_WIDTH = 720;
/** MapLibre's tile size in CSS pixels. */
const TILE = 512;

/** The screen, in CSS pixels, the foot of the search strip over the map, and the panel on it. */
export interface Screen {
  readonly width: number;
  readonly height: number;
  readonly top: number;
  /** The school's panel as it is on the screen now, the sheet as far up as it is; none if closed. */
  readonly panel?: Area | undefined;
}

/** A part of the screen, in CSS pixels from its top left corner. */
export interface Area {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
}

/**
 * The part of the map a school's panel leaves in view, below the search
 * strip: right of the panel beside the map, above the sheet on a phone (at
 * the height it opens to). A pick puts its school in the middle of it.
 */
export function openArea(screen: Screen): Area {
  const { width, height, top } = screen;
  return width < PHONE_WIDTH
    ? { left: 0, top, right: width, bottom: height - Math.round(height * OPEN_SHARE) }
    : { left: PANEL_EDGE + panelWidth(width), top, right: width, bottom: height };
}

/**
 * The part of the map in view now, below the search strip: right of the
 * school's panel beside the map, above its sheet on a phone as far up as the
 * sheet is, and all of it while no panel shows (or one with no box). A tap on
 * several schools zooms them into it (map/school-taps.ts). The menu needs no
 * room: a press on the map closes it (ui/MenuPanel.svelte).
 */
export function mapInView(screen: Screen): Area {
  const { width, height, top, panel } = screen;
  if (panel === undefined || !(panel.bottom > panel.top)) {
    return { left: 0, top, right: width, bottom: height };
  }
  return width < PHONE_WIDTH
    ? { left: 0, top, right: width, bottom: Math.min(Math.max(panel.top, top), height) }
    : { left: Math.min(Math.max(panel.right, 0), width), top, right: width, bottom: height };
}

/** Where a place lies in the world at zoom 0, in CSS pixels (one 512-pixel tile). */
function toWorld(lon: number, lat: number): { x: number; y: number } {
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * TILE,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * TILE,
  };
}

/** The place at a point of the world at zoom 0. */
function fromWorld(x: number, y: number): { lon: number; lat: number } {
  return {
    lon: (x / TILE) * 360 - 180,
    lat: (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / TILE))) * 180) / Math.PI,
  };
}

/** The view that shows `view`'s middle in the middle of the map the panel leaves in view. */
export function clearOfPanel(view: MapView, screen: Screen): MapView {
  const { width, height } = screen;
  const area = openArea(screen);
  // Where the place goes, from the screen's middle, in pixels at zoom 0.
  const scale = 2 ** view.zoom;
  const dx = ((area.left + area.right) / 2 - width / 2) / scale;
  const dy = ((area.top + area.bottom) / 2 - height / 2) / scale;
  const at = toWorld(view.lon, view.lat);
  return { ...fromWorld(at.x - dx, at.y - dy), zoom: view.zoom };
}

/** Room left around the places a view fits, in CSS pixels: their dots and names stay clear of the edges. */
export const FIT_PADDING = 48;

/**
 * The view that shows a box, [west, south, east, north], whole in the middle
 * of the map the panel leaves in view, FIT_PADDING clear of its edges, and
 * no closer than `maxZoom`: the schools around a ZIP code, beside its panel
 * or above its sheet.
 */
export function fitClearOfPanel(
  bounds: readonly [number, number, number, number],
  screen: Screen,
  maxZoom: number,
): MapView {
  const [west, south, east, north] = bounds;
  const area = openArea(screen);
  const room = {
    width: Math.max(1, area.right - area.left - 2 * FIT_PADDING),
    height: Math.max(1, area.bottom - area.top - 2 * FIT_PADDING),
  };
  const corner = toWorld(west, north);
  const across = toWorld(east, south);
  const fits = [
    maxZoom,
    Math.log2(room.width / (across.x - corner.x)),
    Math.log2(room.height / (across.y - corner.y)),
  ];
  const middle = fromWorld((corner.x + across.x) / 2, (corner.y + across.y) / 2);
  return clearOfPanel({ ...middle, zoom: Math.min(...fits) }, screen);
}

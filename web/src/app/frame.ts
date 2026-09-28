/**
 * Where the map looks to show a school its detail panel has opened for: the
 * school in the middle of the map the panel leaves in view, right of the
 * panel beside the map, above the sheet on a phone (at the height the sheet
 * opens to, ui/sheet-geometry.ts), and below the search strip either way.
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

/** The screen, in CSS pixels, and the foot of the search strip over the map. */
export interface Screen {
  readonly width: number;
  readonly height: number;
  readonly top: number;
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
 * the height it opens to). A pick puts its school in the middle of it, and a
 * tap on several schools zooms them into it (map/school-taps.ts).
 */
export function openArea(screen: Screen): Area {
  const { width, height, top } = screen;
  return width < PHONE_WIDTH
    ? { left: 0, top, right: width, bottom: height - Math.round(height * OPEN_SHARE) }
    : { left: PANEL_EDGE + panelWidth(width), top, right: width, bottom: height };
}

/** The view that shows `view`'s middle in the middle of the map the panel leaves in view. */
export function clearOfPanel(view: MapView, screen: Screen): MapView {
  const { width, height } = screen;
  const area = openArea(screen);
  // Where the place goes, from the screen's middle, in pixels.
  const dx = (area.left + area.right) / 2 - width / 2;
  const dy = (area.top + area.bottom) / 2 - height / 2;
  const scale = TILE * 2 ** view.zoom;
  const x = ((view.lon + 180) / 360) * scale - dx;
  const sin = Math.sin((view.lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale - dy;
  const lon = (x / scale) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / scale))) * 180) / Math.PI;
  return { lat, lon, zoom: view.zoom };
}

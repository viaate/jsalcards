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

/** The panel's width and its gap from the screen's edge beside the map (DetailPanel.svelte). */
export const PANEL_WIDTH = 368;
export const PANEL_EDGE = 20;
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

/** The view that shows `view`'s middle in the middle of the map the panel leaves in view. */
export function clearOfPanel(view: MapView, screen: Screen): MapView {
  const { width, height, top } = screen;
  const covered =
    width < PHONE_WIDTH
      ? { left: 0, bottom: Math.round(height * OPEN_SHARE) }
      : { left: PANEL_EDGE + PANEL_WIDTH, bottom: 0 };
  // Where the place goes, from the screen's middle, in pixels.
  const dx = covered.left / 2;
  const dy = (top + height - covered.bottom) / 2 - height / 2;
  const scale = TILE * 2 ** view.zoom;
  const x = ((view.lon + 180) / 360) * scale - dx;
  const sin = Math.sin((view.lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale - dy;
  const lon = (x / scale) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / scale))) * 180) / Math.PI;
  return { lat, lon, zoom: view.zoom };
}

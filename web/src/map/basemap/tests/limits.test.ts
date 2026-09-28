// @vitest-environment node
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { formatView, parseView } from '../../../state/url';
import {
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
} from '../../glow/mercator';
import { CENTER_BOUNDS, MAX_ZOOM, MIN_ZOOM } from '../bounds';
import type { MapView } from '../bounds';
import { NEARBY_ZOOM, ZOOM_SLACK, constrainView, nearUs, screenBox, viewLimits } from '../limits';
import type { Box, Insets, Place, ViewLimits } from '../limits';
import { US_BOUNDS, US_LINES_FILE } from '../us-geo';

/**
 * The frame index.html lays out: the top strip and a gap above it, the sides
 * and the bottom inset. A phone stacks the wordmark over a taller field and
 * keeps the legend's line clear at the bottom.
 */
function frameInsets(width: number): Insets {
  const phone = width <= 719;
  const top = phone ? 16 + 40 + 48 + 24 : 20 + 44 + 24;
  const side = phone ? 16 : 48;
  return { top, right: side, bottom: phone ? 68 : 48, left: side };
}

/** Every screen the map is held to, portrait and landscape, phones to large desktops. */
const SCREENS: readonly (readonly [number, number])[] = [
  [320, 568],
  [568, 320],
  [375, 667],
  [390, 844],
  [844, 390],
  [768, 1024],
  [1024, 768],
  [1280, 800],
  [1440, 900],
  [1565, 957],
  [1920, 1080],
  [1080, 1920],
  [2560, 1440],
  [1440, 2560],
];

const limitsFor = ([width, height]: readonly [number, number]): ViewLimits =>
  viewLimits({ width, height }, frameInsets(width));

const US_BOX: Box = {
  x0: mercatorXFromLng(US_BOUNDS[0]),
  y0: mercatorYFromLat(US_BOUNDS[3]),
  x1: mercatorXFromLng(US_BOUNDS[2]),
  y1: mercatorYFromLat(US_BOUNDS[1]),
};

/** Pixels per world unit at a zoom, for 512 px tiles. */
const scaleAt = (zoom: number): number => 512 * 2 ** zoom;

function worldPoint(view: MapView): [number, number] {
  return [mercatorXFromLng(view.lon), mercatorYFromLat(view.lat)];
}

/** Distance between two views' centers in screen pixels at `zoom`. */
function pixelsApart(a: MapView, b: MapView, zoom: number): number {
  const [ax, ay] = worldPoint(a);
  const [bx, by] = worldPoint(b);
  return Math.hypot(ax - bx, ay - by) * scaleAt(zoom);
}

/** A deterministic stream of numbers in [0, 1). */
function randomStream(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 16807) % 2147483647;
    return state / 2147483647;
  };
}

/**
 * The land inside the bundled outline, as a raster of RASTER degrees: each
 * row is filled between the outline's crossings of its middle latitude. The
 * outline is every ring of the bundled land's polygons.
 */
const RASTER = 0.02;
const LAND_RASTER = (() => {
  const path = fileURLToPath(new URL(`../../../../public/${US_LINES_FILE}`, import.meta.url));
  const data = JSON.parse(readFileSync(path, 'utf8')) as {
    features: { properties: { kind: string }; geometry: { coordinates: unknown } }[];
  };
  const lines = data.features
    .filter((feature) => feature.properties.kind === 'land')
    .flatMap((feature) => (feature.geometry.coordinates as number[][][][]).flat());
  if (lines.length === 0) throw new Error('The bundled file holds no land');
  const [west, south, east, north] = US_BOUNDS;
  const columns = Math.ceil((east - west) / RASTER) + 1;
  const rows = Math.ceil((north - south) / RASTER) + 1;
  const cells = new Uint8Array(columns * rows);
  for (let row = 0; row < rows; row++) {
    const lat = south + (row + 0.5) * RASTER + 1e-7;
    const crossings: number[] = [];
    for (const line of lines) {
      for (let i = 1; i < line.length; i++) {
        const [lng0 = 0, lat0 = 0] = line[i - 1] ?? [];
        const [lng1 = 0, lat1 = 0] = line[i] ?? [];
        if (lat0 < lat === lat1 < lat) continue;
        crossings.push(lng0 + ((lat - lat0) / (lat1 - lat0)) * (lng1 - lng0));
      }
    }
    crossings.sort((a, b) => a - b);
    for (let i = 0; i + 1 < crossings.length; i += 2) {
      const from = Math.floor(((crossings[i] ?? 0) - west) / RASTER);
      const to = Math.floor(((crossings[i + 1] ?? 0) - west) / RASTER);
      for (let column = from; column <= to; column++) cells[row * columns + column] = 1;
    }
    // Shores and islands narrower than a cell still count.
    for (const line of lines) {
      for (const [lng = 0, lat0 = 0] of line) {
        if (Math.abs(lat0 - (south + (row + 0.5) * RASTER)) <= RASTER / 2) {
          cells[row * columns + Math.floor((lng - west) / RASTER)] = 1;
        }
      }
    }
  }
  return { west, south, columns, rows, cells };
})();

/** Whether any land lies inside a box, in world units. */
function landInside(box: Box): boolean {
  const { west, south, columns, rows, cells } = LAND_RASTER;
  const c0 = Math.max(0, Math.floor((lngFromMercatorX(box.x0) - west) / RASTER));
  const c1 = Math.min(columns - 1, Math.floor((lngFromMercatorX(box.x1) - west) / RASTER));
  const r0 = Math.max(0, Math.floor((latFromMercatorY(box.y1) - south) / RASTER));
  const r1 = Math.min(rows - 1, Math.floor((latFromMercatorY(box.y0) - south) / RASTER));
  for (let row = r0; row <= r1; row++) {
    for (let column = c0; column <= c1; column++) {
      if (cells[row * columns + column] === 1) return true;
    }
  }
  return false;
}

/** Requested centers far off in eight directions, plus the fit itself. */
function farCenters(fit: MapView): MapView[] {
  const views: MapView[] = [];
  for (const dLat of [-40, 0, 40]) {
    for (const dLon of [-80, 0, 80]) {
      views.push({ lat: fit.lat + dLat, lon: fit.lon + dLon, zoom: fit.zoom });
    }
  }
  return views;
}

describe('the national view', () => {
  it('fits the continental US into the frame, centered in it', () => {
    for (const screen of SCREENS) {
      const [width, height] = screen;
      const limits = limitsFor(screen);
      const insets = frameInsets(width);
      const frameWidth = width - insets.left - insets.right;
      const frameHeight = height - insets.top - insets.bottom;
      const scale = scaleAt(limits.fit.zoom);
      const usWidth = (US_BOX.x1 - US_BOX.x0) * scale;
      const usHeight = (US_BOX.y1 - US_BOX.y0) * scale;
      // Fills the frame on its tighter axis, and fits on the other.
      expect(Math.max(usWidth / frameWidth, usHeight / frameHeight)).toBeCloseTo(1, 9);
      // Centered in the frame, as MapLibre's fitBounds places it.
      const [x, y] = worldPoint(limits.fit);
      const left = width / 2 - (x - US_BOX.x0) * scale;
      const top = height / 2 - (y - US_BOX.y0) * scale;
      expect(left - insets.left).toBeCloseTo((frameWidth - usWidth) / 2, 6);
      expect(top - insets.top).toBeCloseTo((frameHeight - usHeight) / 2, 6);
    }
  });

  it('is always allowed, exactly, so nothing moves on load or at the handover', () => {
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      expect(constrainView(limits, limits.fit)).toEqual(limits.fit);
    }
  });
});

/**
 * Where the country is drawn at a view, on a screen of `width` by `height`:
 * its box in CSS pixels.
 */
function drawnUs(view: MapView, width: number, height: number): Box {
  const scale = scaleAt(view.zoom);
  const [x, y] = worldPoint(view);
  return {
    x0: width / 2 + (US_BOX.x0 - x) * scale,
    y0: height / 2 + (US_BOX.y0 - y) * scale,
    x1: width / 2 + (US_BOX.x1 - x) * scale,
    y1: height / 2 + (US_BOX.y1 - y) * scale,
  };
}

/** Kansas City, Missouri, where a phone's viewer is in these tests. */
const KANSAS_CITY: Place = { lat: 39.0997, lon: -94.5786 };

describe('the home view', () => {
  it('is the national view itself, the same object, where the viewer is not known', () => {
    for (const screen of SCREENS) {
      const [width, height] = screen;
      const limits = limitsFor(screen);
      expect(limits.home).toBe(limits.fit);
      const unknown = viewLimits({ width, height }, frameInsets(width), null);
      expect(unknown.home).toBe(unknown.fit);
      expect(unknown).toEqual(limits);
    }
  });

  it('shows a phone the whole country, from one side of the page to the other, nothing cropped', () => {
    for (const [width, height] of SCREENS.filter(([w, h]) => w <= 719 && h >= w)) {
      const where = `${String(width)}x${String(height)}`;
      const insets = frameInsets(width);
      const limits = viewLimits({ width, height }, insets);
      const us = drawnUs(limits.home, width, height);
      // As wide as the frame, the page's side margins either side, and centered down it.
      expect(us.x0, where).toBeCloseTo(insets.left, 6);
      expect(us.x1, where).toBeCloseTo(width - insets.right, 6);
      const frameMiddle = (insets.top + height - insets.bottom) / 2;
      expect((us.y0 + us.y1) / 2, where).toBeCloseTo(frameMiddle, 6);
      expect(us.y0, where).toBeGreaterThan(insets.top);
      expect(us.y1, where).toBeLessThan(height - insets.bottom);
    }
  });

  it("opens over the viewer's own area, at NEARBY_ZOOM, centered in the frame", () => {
    for (const screen of SCREENS) {
      const [width, height] = screen;
      const where = `${String(width)}x${String(height)}`;
      const insets = frameInsets(width);
      const limits = viewLimits({ width, height }, insets, KANSAS_CITY);
      expect(limits.home.zoom, where).toBe(NEARBY_ZOOM);
      // Kansas City at the frame's middle, between the search field and the legend.
      const scale = scaleAt(NEARBY_ZOOM);
      const [x, y] = worldPoint(limits.home);
      const [kx, ky] = worldPoint({ ...KANSAS_CITY, zoom: NEARBY_ZOOM });
      expect(width / 2 + (kx - x) * scale, where).toBeCloseTo(
        (insets.left + width - insets.right) / 2,
        6,
      );
      expect(height / 2 + (ky - y) * scale, where).toBeCloseTo(
        (insets.top + height - insets.bottom) / 2,
        6,
      );
      // The national view stays what zooming out stops at, and the home view is allowed as it is.
      expect(limits.fit).toEqual(limitsFor(screen).fit);
      expect(limits.minZoom).toBe(limitsFor(screen).minZoom);
      expect(constrainView(limits, limits.home), where).toEqual(limits.home);
    }
  });

  it('holds a viewer by a shore or a border to the nearest view the limits allow', () => {
    const [width, height] = [390, 844];
    // Key West, and Point Roberts across the water from the rest of Washington.
    for (const place of [
      { lat: 24.5551, lon: -81.78 },
      { lat: 48.985, lon: -123.068 },
    ]) {
      const limits = viewLimits({ width, height }, frameInsets(width), place);
      expect(limits.home).not.toBe(limits.fit);
      expect(limits.home.zoom).toBe(NEARBY_ZOOM);
      expect(constrainView(limits, limits.home)).toEqual(limits.home);
    }
  });

  it('opens on the national view for a viewer off the continental US, or nowhere', () => {
    const [width, height] = [390, 844];
    for (const place of [
      { lat: 43.6532, lon: -79.3832 },
      { lat: 21.3069, lon: -157.8583 },
      { lat: 61.2181, lon: -149.9003 },
      { lat: 19.4326, lon: -99.1332 },
      { lat: 51.5072, lon: -0.1276 },
      { lat: Number.NaN, lon: -94.58 },
    ]) {
      const limits = viewLimits({ width, height }, frameInsets(width), place);
      expect(limits.home, JSON.stringify(place)).toBe(limits.fit);
    }
    const none = viewLimits({ width: 0, height: 0 }, frameInsets(0), KANSAS_CITY);
    expect(none.home.zoom).toBe(NEARBY_ZOOM);
  });
});

describe('nearUs', () => {
  it('takes in the continental US, its islands and a shore, and nothing far past it', () => {
    for (const place of [
      KANSAS_CITY,
      { lat: 47.6062, lon: -122.3321 },
      { lat: 25.7617, lon: -80.1918 },
      { lat: 44.3876, lon: -68.2039 },
      { lat: 42.3314, lon: -83.0458 },
      { lat: 43.7684, lon: -69.3167 },
    ]) {
      expect(nearUs(place), JSON.stringify(place)).toBe(true);
    }
    for (const place of [
      { lat: 43.6532, lon: -79.3832 },
      { lat: 49.2827, lon: -123.1207 },
      { lat: 21.3069, lon: -157.8583 },
      { lat: 19.4326, lon: -99.1332 },
      { lat: 30, lon: -60 },
    ]) {
      expect(nearUs(place), JSON.stringify(place)).toBe(false);
    }
  });
});

describe('zooming out', () => {
  it('stops a little past the national view, never half a level past it', () => {
    expect(ZOOM_SLACK).toBeGreaterThan(0);
    expect(ZOOM_SLACK).toBeLessThanOrEqual(0.5);
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      expect(limits.minZoom).toBeCloseTo(limits.fit.zoom - ZOOM_SLACK, 12);
      expect(limits.minZoom).toBeGreaterThanOrEqual(MIN_ZOOM);
      for (const zoom of [-5, 0, MIN_ZOOM, limits.minZoom - 0.01, Number.NaN]) {
        const view = constrainView(limits, { ...limits.fit, zoom });
        expect(view.zoom).toBe(Number.isNaN(zoom) ? limits.fit.zoom : limits.minZoom);
      }
      expect(constrainView(limits, { ...limits.fit, zoom: 30 }).zoom).toBe(MAX_ZOOM);
    }
  });

  it('keeps the whole country on screen at the widest zoom, wherever it is dragged', () => {
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      const insets = frameInsets(screen[0]);
      for (const far of farCenters(limits.fit)) {
        const view = constrainView(limits, { ...far, zoom: limits.minZoom });
        const shown = screenBox(limits, view);
        const scale = scaleAt(view.zoom);
        // The whole outline is on screen, below the search bar.
        expect(US_BOX.x0).toBeGreaterThanOrEqual(shown.x0);
        expect(US_BOX.x1).toBeLessThanOrEqual(shown.x1);
        expect((US_BOX.y0 - shown.y0) * scale).toBeGreaterThanOrEqual(insets.top - 24);
        expect(US_BOX.y1).toBeLessThanOrEqual(shown.y1);
        // And about as large as at the national view.
        expect((US_BOX.x1 - US_BOX.x0) * scale).toBeGreaterThan(
          (US_BOX.x1 - US_BOX.x0) * scaleAt(limits.fit.zoom) * 2 ** -0.5,
        );
      }
    }
  });
});

/** Whether land shows on screen at a view, the screen grown on every side by `grow` degrees. */
function landShown(limits: ViewLimits, view: MapView, grow = 0): boolean {
  const shown = screenBox(limits, view);
  const dx = mercatorXFromLng(grow) - mercatorXFromLng(0);
  const dy = mercatorYFromLat(view.lat - grow) - mercatorYFromLat(view.lat);
  return landInside({ x0: shown.x0 - dx, y0: shown.y0 - dy, x1: shown.x1 + dx, y1: shown.y1 + dy });
}

/**
 * Whether land shows in the middle half of the frame (the screen less the
 * page's bars and their gaps), across and down, give or take `grow` degrees:
 * the land map's bands and shore slack.
 */
function landInMiddle(limits: ViewLimits, view: MapView, grow: number): boolean {
  const insets = frameInsets(limits.width);
  const scale = scaleAt(view.zoom);
  const [screenX, screenY] = worldPoint(view);
  // The frame's center, and a quarter of its width and height, in world units.
  const x = screenX + (insets.left - insets.right) / 2 / scale;
  const y = screenY + (insets.top - insets.bottom) / 2 / scale;
  const quarterX = (limits.width - insets.left - insets.right) / 4 / scale;
  const quarterY = (limits.height - insets.top - insets.bottom) / 4 / scale;
  const dx = mercatorXFromLng(grow) - mercatorXFromLng(0);
  const dy = mercatorYFromLat(view.lat - grow) - screenY;
  return landInside({
    x0: x - quarterX - dx,
    y0: y - quarterY - dy,
    x1: x + quarterX + dx,
    y1: y + quarterY + dy,
  });
}

/** One frame of a drag: the view moved by (dx, dy) screen pixels, then held to the limits. */
function drag(limits: ViewLimits, view: MapView, dx: number, dy: number): MapView {
  const [x, y] = worldPoint(view);
  const scale = scaleAt(view.zoom);
  const nx = x + dx / scale;
  const ny = y + dy / scale;
  return constrainView(limits, {
    lat: (360 / Math.PI) * Math.atan(Math.exp(Math.PI * (1 - 2 * ny))) - 90,
    lon: nx * 360 - 180,
    zoom: view.zoom,
  });
}

describe('panning', () => {
  it('keeps the country on screen at every zoom, dragged as far as it goes', () => {
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      for (let zoom = limits.minZoom; zoom <= 13; zoom += 0.5) {
        for (const far of farCenters(limits.fit)) {
          const view = constrainView(limits, { ...far, zoom });
          const where = `${String(screen)} z${zoom.toFixed(1)} toward ${far.lat.toFixed(0)},${far.lon.toFixed(0)}`;
          // Land in the middle half of the frame, clear of the page's bars, give or take the land
          // map's band and shore slack.
          expect(landInMiddle(limits, view, 0.16), where).toBe(true);
          // Up to regional zoom, where a band of the land map is small beside the screen, that land is on screen outright.
          if (zoom <= 9) expect(landShown(limits, view), where).toBe(true);
        }
      }
    }
  });

  it('stops at the nearest coast or border, not out over open water or abroad', () => {
    const limits = limitsFor([1565, 957]);
    const cases: { from: MapView; near: [number, number] }[] = [
      // Out to sea off Jacksonville, at city zoom.
      { from: { lat: 30.5, lon: -80.0, zoom: 12 }, near: [30.5, -81.4] },
      // Far out in the Atlantic: the nearest shore is Cape Hatteras.
      { from: { lat: 32.0, lon: -70, zoom: 12 }, near: [35.2, -75.5] },
      // South of New Orleans into the Gulf.
      { from: { lat: 26.0, lon: -90.07, zoom: 10 }, near: [28.9, -89.8] },
      // North of Montana into Canada.
      { from: { lat: 55, lon: -110, zoom: 8 }, near: [49.2, -110] },
      // Out over the Pacific west of San Francisco: back to the coast by Bodega Bay.
      { from: { lat: 37.77, lon: -124.5, zoom: 11 }, near: [38.2, -123.3] },
      // Into Ontario between Detroit and Buffalo: back to Niagara, New York.
      { from: { lat: 43.6, lon: -80.6, zoom: 10 }, near: [43.35, -79.2] },
      // Into Mexico south of Nogales, Arizona.
      { from: { lat: 30.3, lon: -110.94, zoom: 11 }, near: [31.3, -110.94] },
    ];
    for (const { from, near } of cases) {
      const view = constrainView(limits, from);
      const where = `from ${String(from.lat)},${String(from.lon)} z${String(from.zoom)}`;
      expect(landShown(limits, view, 0.06), where).toBe(true);
      expect(Math.abs(view.lat - near[0]), where).toBeLessThan(0.5);
      expect(Math.abs(view.lon - near[1]), where).toBeLessThan(0.5);
    }
  });

  it('reaches every corner of the country at street zoom, and pans across lakes and bays', () => {
    const limits = limitsFor([1565, 957]);
    const places: MapView[] = [
      { lat: 39.03606, lon: -94.593001, zoom: 16 }, // Pembroke Hill, Kansas City
      { lat: 24.5465, lon: -81.7975, zoom: 16 }, // Key West
      { lat: 48.3831, lon: -124.715, zoom: 16 }, // Cape Flattery
      { lat: 44.8151, lon: -66.9503, zoom: 16 }, // West Quoddy Head
      { lat: 49.3539, lon: -95.0728, zoom: 16 }, // Northwest Angle
      { lat: 25.9017, lon: -97.4975, zoom: 16 }, // Brownsville
      { lat: 33.3428, lon: -118.3278, zoom: 16 }, // Avalon, Catalina Island
      { lat: 48.9853, lon: -123.0712, zoom: 16 }, // Point Roberts
      { lat: 41.2835, lon: -70.0995, zoom: 16 }, // Nantucket
      { lat: 43.5, lon: -87.0, zoom: 12 }, // the middle of Lake Michigan
      { lat: 37.9, lon: -76.1, zoom: 12 }, // the middle of Chesapeake Bay
      { lat: 35.3, lon: -75.9, zoom: 12 }, // Pamlico Sound
    ];
    for (const place of places) expect(constrainView(limits, place)).toEqual(place);
  });

  it('comes back unchanged when asked twice', () => {
    const random = randomStream(11);
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      for (let i = 0; i < 150; i++) {
        const view = constrainView(limits, {
          lat: -80 + random() * 160,
          lon: -180 + random() * 360,
          zoom: random() * 18 - 1,
        });
        expect(constrainView(limits, view)).toEqual(view);
      }
    }
  });

  it('slides along every edge without jumping or shaking', () => {
    // Every frame of every drag is checked; the ones that fail are listed, and the list must be
    // empty (one expectation, not hundreds of thousands).
    const failures: string[] = [];
    for (const screen of [
      [1565, 957],
      [390, 844],
      [844, 390],
    ] as const) {
      const limits = limitsFor(screen);
      const zooms = [limits.minZoom, limits.fit.zoom, limits.fit.zoom + 1, limits.fit.zoom + 2];
      for (const zoom of [...zooms, 7, 9]) {
        for (let angle = 0; angle < 360; angle += 20) {
          // A hard drag, 40 px a frame for 500 frames: far past any edge at these zooms.
          const dx = Math.cos((angle * Math.PI) / 180) * 40;
          const dy = Math.sin((angle * Math.PI) / 180) * 40;
          let view = constrainView(limits, { ...limits.fit, zoom });
          const path: MapView[] = [view];
          for (let frame = 0; frame < 500; frame++) {
            view = drag(limits, view, dx, dy);
            path.push(view);
          }
          const where = `${String(screen)} z${zoom.toFixed(2)} at ${String(angle)} degrees`;
          for (let i = 1; i < path.length; i++) {
            const previous = path[i - 1] ?? view;
            const current = path[i] ?? view;
            // No frame moves further than the drag and the slide along an edge together.
            const moved = pixelsApart(current, previous, zoom);
            if (!(moved <= 80 + 1e-6))
              failures.push(`${where}, frame ${String(i)}: jumps ${String(moved)} px`);
            // Never back toward where it was two frames before: no shaking at an edge.
            const before = path[i - 2];
            if (before === undefined) continue;
            const step = pixelsApart(previous, before, zoom);
            if (step > 1 && !(pixelsApart(current, before, zoom) > step * 0.5)) {
              failures.push(`${where}, frame ${String(i)}: shakes`);
            }
          }
          // And the country is still on screen at the end.
          if (!landShown(limits, view)) failures.push(`${where}: the country is off screen`);
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('moves smoothly when zooming out against an edge', () => {
    const limits = limitsFor([1565, 957]);
    let view = constrainView(limits, { lat: 32.0, lon: -60, zoom: 12 });
    while (view.zoom > limits.minZoom) {
      const next = constrainView(limits, { ...view, zoom: view.zoom - 0.05 });
      // The center shifts by no more than the screen does as it shrinks around it.
      expect(pixelsApart(next, view, next.zoom)).toBeLessThan(957 * 0.05);
      view = next;
    }
    expect(view.zoom).toBe(limits.minZoom);
  });

  it('follows the screen: the new limits apply to the view the old screen allowed', () => {
    const wide = limitsFor([2560, 1440]);
    const narrow = limitsFor([390, 844]);
    expect(narrow.minZoom).toBeLessThan(wide.minZoom);
    const widest = constrainView(narrow, { ...narrow.fit, zoom: narrow.minZoom });
    const onWide = constrainView(wide, widest);
    expect(onWide.zoom).toBe(wide.minZoom);
  });

  it('copes with a frame or a screen with no area', () => {
    const short = viewLimits({ width: 800, height: 100 }, frameInsets(800));
    expect(Number.isFinite(short.fit.zoom)).toBe(true);
    expect(constrainView(short, short.fit)).toEqual(short.fit);
    const none = viewLimits({ width: 0, height: 0 }, frameInsets(0));
    const view = constrainView(none, { lat: 0, lon: 0, zoom: 0 });
    expect(Number.isFinite(view.lat) && Number.isFinite(view.lon)).toBe(true);
  });
});

/** A school's federal id and where the directory puts it. */
interface School {
  readonly id: string;
  readonly lon: number;
  readonly lat: number;
}

/** The schools the outline misses, which build-geo.mjs folds into the land map. */
const REACH_SCHOOLS = (
  JSON.parse(
    readFileSync(
      fileURLToPath(new URL('../../../../scripts/reach-schools.json', import.meta.url)),
      'utf8',
    ),
  ) as { schools: School[] }
).schools;

/** The school directory the pipeline writes, when it has been built here (not in CI). */
const POINTS_FILE = fileURLToPath(
  new URL('../../../../../pipeline/out/site-data/schools/points.bin', import.meta.url),
);

/** Every school's location in points.bin: a 16-byte header, then 13 bytes per school. */
function directoryLocations(): Float64Array {
  const bytes = readFileSync(POINTS_FILE);
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  expect(bytes.subarray(0, 4).toString('latin1')).toBe('SLPT');
  expect(data.getUint16(6, true)).toBe(13);
  const count = data.getUint32(8, true);
  expect(bytes.length).toBe(16 + 13 * count);
  const locations = new Float64Array(count * 2);
  for (let i = 0; i < count; i++) {
    locations[i * 2] = data.getInt32(16 + 13 * i, true) / 1e6;
    locations[i * 2 + 1] = data.getInt32(16 + 13 * i + 4, true) / 1e6;
  }
  return locations;
}

describe('schools', () => {
  it('can each be centered at street zoom, on every screen, the ones on islands the outline leaves out too', () => {
    // Monhegan School, on its island ten miles off the coast of Maine.
    expect(REACH_SCHOOLS).toContainEqual({ id: '230834000229', lon: -69.318376, lat: 43.765918 });
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      for (const { id, lon, lat } of REACH_SCHOOLS) {
        for (const zoom of [8, 10, 12, 14, 15, MAX_ZOOM]) {
          const view = { lat, lon, zoom };
          expect(
            constrainView(limits, view),
            `${id} on ${String(screen)} at z${String(zoom)}`,
          ).toEqual(view);
        }
      }
    }
  });

  it('can be panned around at street zoom, not only reached', () => {
    const limits = limitsFor([1565, 957]);
    const monhegan = { lat: 43.765918, lon: -69.318376, zoom: MAX_ZOOM };
    for (let angle = 0; angle < 360; angle += 45) {
      // Half a screen away in each direction, then back: the view follows.
      const dx = Math.cos((angle * Math.PI) / 180) * 480;
      const dy = Math.sin((angle * Math.PI) / 180) * 480;
      const away = drag(limits, monhegan, dx, dy);
      expect(pixelsApart(away, monhegan, MAX_ZOOM), String(angle)).toBeCloseTo(480, 3);
      expect(pixelsApart(drag(limits, away, -dx, -dy), monhegan, MAX_ZOOM)).toBeLessThan(1e-3);
    }
  });

  it.skipIf(!existsSync(POINTS_FILE))(
    'every school in the directory can be centered at street zoom',
    () => {
      const locations = directoryLocations();
      expect(locations.length / 2).toBeGreaterThan(100_000);
      for (const screen of [
        [320, 568],
        [390, 844],
        [1565, 957],
        [2560, 1440],
      ] as const) {
        const limits = limitsFor(screen);
        for (const zoom of [8, 12, 15, MAX_ZOOM]) {
          const missed: string[] = [];
          for (let i = 0; i < locations.length; i += 2) {
            const view = { lon: locations[i] ?? NaN, lat: locations[i + 1] ?? NaN, zoom };
            const allowed = constrainView(limits, view);
            if (allowed.lat !== view.lat || allowed.lon !== view.lon || allowed.zoom !== zoom) {
              missed.push(`${String(view.lat)},${String(view.lon)}`);
            }
          }
          expect(missed, `${String(screen)} at z${String(zoom)}`).toEqual([]);
        }
      }
    },
    120_000,
  );
});

describe('links', () => {
  it('hold every view the map allows, so a shared view opens where it was', () => {
    const random = randomStream(5);
    const [west, south, east, north] = CENTER_BOUNDS;
    for (const screen of SCREENS) {
      const limits = limitsFor(screen);
      for (let i = 0; i < 100; i++) {
        const view = constrainView(limits, {
          lat: -80 + random() * 160,
          lon: -180 + random() * 360,
          zoom: random() * 18 - 1,
        });
        expect(view.lat).toBeGreaterThanOrEqual(south);
        expect(view.lat).toBeLessThanOrEqual(north);
        expect(view.lon).toBeGreaterThanOrEqual(west);
        expect(view.lon).toBeLessThanOrEqual(east);
        expect(view.zoom).toBeGreaterThanOrEqual(MIN_ZOOM);
        // The link, opened on the same screen, lands within a few pixels of it.
        const link = parseView(formatView(view));
        expect(link).not.toBeNull();
        if (link === null) continue;
        const opened = constrainView(limits, link);
        expect(Math.abs(opened.zoom - view.zoom)).toBeLessThanOrEqual(0.005);
        expect(pixelsApart(opened, view, view.zoom)).toBeLessThan(5);
      }
    }
  });

  it('open a view outside the limits at the nearest allowed one', () => {
    const limits = limitsFor([1565, 957]);
    const link = parseView('0,0,0');
    expect(link).not.toBeNull();
    if (link === null) return;
    const view = constrainView(limits, link);
    expect(view.zoom).toBe(limits.minZoom);
    // At the widest zoom the whole country is on screen.
    const shown = screenBox(limits, view);
    expect(US_BOX.x0).toBeGreaterThanOrEqual(shown.x0);
    expect(US_BOX.x1).toBeLessThanOrEqual(shown.x1);
  });
});

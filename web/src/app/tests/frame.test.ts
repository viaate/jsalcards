import { describe, expect, it } from 'vitest';

import { OPEN_SHARE } from '../../ui/sheet-geometry';
import { PANEL_EDGE, PANEL_WIDTH, clearOfPanel, mapInView, openArea, panelWidth } from '../frame';

/** Pembroke Hill, on its streets. */
const SCHOOL = { lat: 39.03606, lon: -94.593001, zoom: 15 };

/** Where a place lies in the world at `zoom`, in CSS pixels (512-pixel tiles). */
function worldPixels(lat: number, lon: number, zoom: number): { x: number; y: number } {
  const scale = 512 * 2 ** zoom;
  const sin = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

/** Where the school lands on the screen with the map centered on `center`. */
function onScreen(
  center: { lat: number; lon: number; zoom: number },
  screen: { width: number; height: number },
): { x: number; y: number } {
  const school = worldPixels(SCHOOL.lat, SCHOOL.lon, center.zoom);
  const middle = worldPixels(center.lat, center.lon, center.zoom);
  return {
    x: screen.width / 2 + school.x - middle.x,
    y: screen.height / 2 + school.y - middle.y,
  };
}

describe('clearOfPanel', () => {
  it('on a phone, puts the school in the middle of the map between the search strip and the sheet', () => {
    const screen = { width: 390, height: 844, top: 104 };
    const center = clearOfPanel(SCHOOL, screen);
    expect(center.zoom).toBe(SCHOOL.zoom);
    const sheetTop = screen.height - Math.round(screen.height * OPEN_SHARE);
    const at = onScreen(center, screen);
    expect(at.x).toBeCloseTo(screen.width / 2, 6);
    expect(at.y).toBeCloseTo((screen.top + sheetTop) / 2, 6);
  });

  it('beside the map, puts it in the middle of the map right of the panel', () => {
    for (const [width, panel] of [
      [800, PANEL_WIDTH],
      [1023, 368],
      [1024, 420],
      [1279, 420],
      [1280, 460],
      [1440, 460],
    ] as const) {
      const screen = { width, height: 900, top: 64 };
      expect(panelWidth(width)).toBe(panel);
      const at = onScreen(clearOfPanel(SCHOOL, screen), screen);
      expect(at.x).toBeCloseTo((PANEL_EDGE + panel + screen.width) / 2, 6);
      expect(at.y).toBeCloseTo((screen.top + screen.height) / 2, 6);
    }
  });

  it('takes a phone for a screen under 720 pixels wide', () => {
    const phone = onScreen(clearOfPanel(SCHOOL, { width: 719, height: 800, top: 100 }), {
      width: 719,
      height: 800,
    });
    const wide = onScreen(clearOfPanel(SCHOOL, { width: 720, height: 800, top: 100 }), {
      width: 720,
      height: 800,
    });
    expect(phone.x).toBeCloseTo(719 / 2, 6);
    expect(wide.x).toBeGreaterThan(720 / 2);
  });
});

describe('openArea', () => {
  it('is the map right of the panel and under the search strip beside the map', () => {
    expect(openArea({ width: 1440, height: 900, top: 64 })).toEqual({
      left: PANEL_EDGE + panelWidth(1440),
      top: 64,
      right: 1440,
      bottom: 900,
    });
  });

  it('is the map between the search strip and the open sheet on a phone', () => {
    expect(openArea({ width: 390, height: 844, top: 104 })).toEqual({
      left: 0,
      top: 104,
      right: 390,
      bottom: 844 - Math.round(844 * OPEN_SHARE),
    });
  });

  it('has in its middle what clearOfPanel puts there', () => {
    for (const screen of [
      { width: 1440, height: 900, top: 64 },
      { width: 390, height: 844, top: 104 },
    ]) {
      const area = openArea(screen);
      const at = onScreen(clearOfPanel(SCHOOL, screen), screen);
      expect(at.x).toBeCloseTo((area.left + area.right) / 2, 6);
      expect(at.y).toBeCloseTo((area.top + area.bottom) / 2, 6);
    }
  });
});

describe('mapInView', () => {
  /** A box on the screen, as getBoundingClientRect gives it. */
  const box = (left: number, top: number, right: number, bottom: number) => ({
    left,
    top,
    right,
    bottom,
  });
  const desktop = { width: 1440, height: 900, top: 64 };
  const phone = { width: 390, height: 844, top: 104 };

  it('is the whole map under the search strip while no panel shows, on any screen', () => {
    expect(mapInView(desktop)).toEqual(box(0, 64, 1440, 900));
    expect(mapInView({ ...phone, panel: undefined })).toEqual(box(0, 104, 390, 844));
  });

  it('is the map right of a panel beside the map, wherever it ends', () => {
    // As a pick frames its school; wider; shorter, all the same.
    const right = PANEL_EDGE + panelWidth(desktop.width);
    const school = box(PANEL_EDGE, 84, right, 880);
    expect(mapInView({ ...desktop, panel: school })).toEqual(openArea(desktop));
    expect(mapInView({ ...desktop, panel: box(PANEL_EDGE, 84, 552, 880) })).toEqual(
      box(552, 64, 1440, 900),
    );
    expect(mapInView({ ...desktop, panel: box(PANEL_EDGE, 84, right, 200) })).toEqual(
      openArea(desktop),
    );
  });

  it('is the map above a phone’s sheet, as far up as the sheet is', () => {
    // Open, as it opens: what a pick frames its school in.
    const opens = 844 - Math.round(844 * OPEN_SHARE);
    expect(mapInView({ ...phone, panel: box(0, opens, 390, 844 + 300) })).toEqual(openArea(phone));
    // Down to its name alone, and up to just under the strip.
    expect(mapInView({ ...phone, panel: box(0, 744, 390, 1500) })).toEqual(box(0, 104, 390, 744));
    expect(mapInView({ ...phone, panel: box(0, 116, 390, 900) })).toEqual(box(0, 104, 390, 116));
    // Over the strip as it glides, it leaves no map in view, never less.
    expect(mapInView({ ...phone, panel: box(0, 90, 390, 900) })).toEqual(box(0, 104, 390, 104));
  });

  it('takes a phone for a screen under 720 pixels wide', () => {
    expect(mapInView({ width: 719, height: 800, top: 100, panel: box(0, 400, 719, 1200) })).toEqual(
      box(0, 100, 719, 400),
    );
    expect(mapInView({ width: 720, height: 800, top: 100, panel: box(20, 120, 388, 780) })).toEqual(
      box(388, 100, 720, 800),
    );
  });

  it('takes a panel with no box, or gone off the foot of the screen, for none', () => {
    expect(mapInView({ ...desktop, panel: box(0, 0, 0, 0) })).toEqual(mapInView(desktop));
    expect(mapInView({ ...phone, panel: box(0, 0, 0, 0) })).toEqual(mapInView(phone));
    expect(mapInView({ ...phone, panel: box(0, 900, 390, 1700) })).toEqual(mapInView(phone));
  });
});

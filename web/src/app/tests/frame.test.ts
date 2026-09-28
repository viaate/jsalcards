import { describe, expect, it } from 'vitest';

import { OPEN_SHARE } from '../../ui/sheet-geometry';
import { PANEL_EDGE, PANEL_WIDTH, clearOfPanel } from '../frame';

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
    const screen = { width: 1440, height: 900, top: 64 };
    const at = onScreen(clearOfPanel(SCHOOL, screen), screen);
    expect(at.x).toBeCloseTo((PANEL_EDGE + PANEL_WIDTH + screen.width) / 2, 6);
    expect(at.y).toBeCloseTo((screen.top + screen.height) / 2, 6);
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

// @vitest-environment node
/**
 * The states in view a phone's map names closer in (state-areas.ts), from
 * the states' shapes build-geo.mjs writes: every state whose part in the
 * frame has room for its name, where that part has most room, off the city
 * names where it can be, out from under the page's controls, and none that
 * has no room; and of the bundled names, the ones kept where they are.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { mercatorXFromLng, mercatorYFromLat } from '../../glow/mercator';
import type { MapView } from '../bounds';
import { STATE_AREA_MARGIN, keptNames, nameBox, parseStateAreas, stateSpots } from '../state-areas';
import type { ScreenRect, SetName, SpotsOptions, StateArea, StateSpot } from '../state-areas';
import { US_STATES_FILE } from '../us-geo';

const AREAS = ((): StateArea[] => {
  const path = fileURLToPath(new URL(`../../../../public/${US_STATES_FILE}`, import.meta.url));
  const areas = parseStateAreas(JSON.parse(readFileSync(path, 'utf8')) as unknown);
  if (areas === null) throw new Error(`${US_STATES_FILE} is not the states' shapes`);
  return areas;
})();

/** A phone held upright, and the frame index.html leaves the map between the field and the key. */
const SCREEN = { width: 390, height: 844 };
const FRAME: ScreenRect = { x0: 16, y0: 128, x1: 374, y1: 776 };

/** A name's size as a phone sets it at zoom 6 and closer: 10.75 px capitals, spaced. */
const nameSize = (name: string): { width: number; height: number } => ({
  width: name.length * 10.75 * 0.85,
  height: 10.75 * 1.2,
});

function spots(view: MapView, options: Partial<SpotsOptions> = {}): StateSpot[] {
  return stateSpots(AREAS, { view, screen: SCREEN, frame: FRAME, nameSize, ...options });
}

/** Where a place is on the screen at a view. */
function onScreen(view: MapView, lon: number, lat: number): { x: number; y: number } {
  const scale = 512 * 2 ** view.zoom;
  return {
    x: SCREEN.width / 2 + (mercatorXFromLng(lon) - mercatorXFromLng(view.lon)) * scale,
    y: SCREEN.height / 2 + (mercatorYFromLat(lat) - mercatorYFromLat(view.lat)) * scale,
  };
}

/** The state a screen point is in, by the shapes. */
function stateAt(view: MapView, x: number, y: number): string | null {
  const scale = 512 * 2 ** view.zoom;
  const worldX = mercatorXFromLng(view.lon) + (x - SCREEN.width / 2) / scale;
  const worldY = mercatorYFromLat(view.lat) + (y - SCREEN.height / 2) / scale;
  for (const area of AREAS) {
    let odd = false;
    for (const ring of area.rings) {
      for (let i = 0, j = ring.length - 2; i < ring.length; j = i, i += 2) {
        const ax = mercatorXFromLng(ring[j] ?? 0);
        const ay = mercatorYFromLat(ring[j + 1] ?? 0);
        const bx = mercatorXFromLng(ring[i] ?? 0);
        const by = mercatorYFromLat(ring[i + 1] ?? 0);
        if (ay > worldY !== by > worldY && worldX < ((bx - ax) * (worldY - ay)) / (by - ay) + ax) {
          odd = !odd;
        }
      }
    }
    if (odd) return area.name;
  }
  return null;
}

describe("the states' shapes", () => {
  it('are the 48 states, each with its rings', () => {
    expect(AREAS).toHaveLength(48);
    expect(AREAS.map((area) => area.name)).toEqual(
      expect.arrayContaining(['Kansas', 'Missouri', 'Texas', 'Maine', 'Washington', 'Michigan']),
    );
    for (const area of AREAS) {
      expect(area.rings.length, area.name).toBeGreaterThan(0);
      expect(area.west, area.name).toBeLessThan(area.east);
      expect(area.south, area.name).toBeLessThan(area.north);
    }
    // Kansas City, Kansas, and Kansas City, Missouri, either side of the state line.
    const metro: MapView = { lat: 39.1, lon: -94.6, zoom: 10 };
    const kck = onScreen(metro, -94.6275, 39.1142);
    const kcmo = onScreen(metro, -94.5786, 39.0997);
    expect(stateAt(metro, kck.x, kck.y)).toBe('Kansas');
    expect(stateAt(metro, kcmo.x, kcmo.y)).toBe('Missouri');
  });

  it('are read only from a file of that form', () => {
    expect(parseStateAreas(null)).toBeNull();
    expect(parseStateAreas({ states: [{ name: 'Kansas', rings: [[1, 2, 3]] }] })).toBeNull();
    expect(parseStateAreas({ states: [{ name: 1, rings: [] }] })).toBeNull();
    expect(parseStateAreas({ states: [{ name: 'Kansas', rings: [] }] })).toEqual([]);
  });
});

describe('the states in view', () => {
  it('names both states of a metro on the state line, each inside its own, whole in the frame', () => {
    const metro: MapView = { lat: 39.1, lon: -94.58, zoom: 10 };
    const named = spots(metro);
    expect(named.map((spot) => spot.name).sort()).toEqual(['Kansas', 'Missouri']);
    for (const spot of named) {
      const size = nameSize(spot.name);
      expect(stateAt(metro, spot.x, spot.y), spot.name).toBe(spot.name);
      // The whole name, and its margin, in its own state and in the frame.
      for (const [dx, dy] of [
        [-1, -1],
        [1, -1],
        [-1, 1],
        [1, 1],
      ] as const) {
        const x = spot.x + dx * (size.width / 2 + STATE_AREA_MARGIN - 0.5);
        const y = spot.y + dy * (size.height / 2 + STATE_AREA_MARGIN - 0.5);
        expect(stateAt(metro, x, y), `${spot.name} corner`).toBe(spot.name);
        expect(x).toBeGreaterThan(FRAME.x0);
        expect(x).toBeLessThan(FRAME.x1);
        expect(y).toBeGreaterThan(FRAME.y0);
        expect(y).toBeLessThan(FRAME.y1);
      }
    }
  });

  it('names every state in a regional view that has room, and none that has not', () => {
    const region: MapView = { lat: 38.9, lon: -95, zoom: 5 };
    const named = spots(region).map((spot) => spot.name);
    for (const state of ['Kansas', 'Missouri', 'Iowa', 'Nebraska', 'Oklahoma', 'Arkansas']) {
      expect(named, state).toContain(state);
    }
    // Illinois and Colorado show only a sliver at the frame's sides: no room for their names.
    expect(named).not.toContain('Illinois');
    expect(named).not.toContain('Colorado');
    // Each once.
    expect(new Set(named).size).toBe(named.length);
  });

  it('leaves out the states whose own name is drawn, and those with no name', () => {
    const region: MapView = { lat: 38.9, lon: -95, zoom: 5 };
    const named = spots(region, {
      skip: new Set(['Kansas']),
      nameSize: (name) => (name === 'Iowa' ? null : nameSize(name)),
    }).map((spot) => spot.name);
    expect(named).not.toContain('Kansas');
    expect(named).not.toContain('Iowa');
    expect(named).toContain('Missouri');
  });

  it('moves a name off a city name where the state has room, and never out of its state', () => {
    const metro: MapView = { lat: 39.1, lon: -94.58, zoom: 10 };
    const kansas = spots(metro).find((spot) => spot.name === 'Kansas');
    expect(kansas).toBeDefined();
    const { x = 0, y = 0 } = kansas ?? {};
    // A city's name right where the state's would go.
    const city: ScreenRect = { x0: x - 40, y0: y - 12, x1: x + 40, y1: y + 12 };
    const moved = spots(metro, { avoid: [city] }).find((spot) => spot.name === 'Kansas');
    expect(moved).toBeDefined();
    const size = nameSize('Kansas');
    const apart =
      (moved?.x ?? 0) + size.width / 2 <= city.x0 ||
      (moved?.x ?? 0) - size.width / 2 >= city.x1 ||
      (moved?.y ?? 0) + size.height / 2 <= city.y0 ||
      (moved?.y ?? 0) - size.height / 2 >= city.y1;
    expect(apart).toBe(true);
    expect(stateAt(metro, moved?.x ?? 0, moved?.y ?? 0)).toBe('Kansas');
  });

  it('names nothing in a frame with no area, or a view of no state', () => {
    expect(
      spots({ lat: 39.1, lon: -94.58, zoom: 10 }, { frame: { x0: 10, y0: 10, x1: 10, y1: 90 } }),
    ).toEqual([]);
    expect(spots({ lat: 30, lon: -60, zoom: 8 })).toEqual([]);
  });

  it("keeps each name out from under the page's controls, or leaves it out", () => {
    const region: MapView = { lat: 38.9, lon: -95, zoom: 5 };
    const before = spots(region);
    const missouri = before.find((spot) => spot.name === 'Missouri');
    expect(missouri).toBeDefined();
    const { x = 0, y = 0 } = missouri ?? {};
    // A button right where Missouri's name would go.
    const button: ScreenRect = { x0: x - 24, y0: y - 24, x1: x + 24, y1: y + 24 };
    const after = spots(region, { blocked: [button] });
    const moved = after.find((spot) => spot.name === 'Missouri');
    expect(moved).toBeDefined();
    const box = nameBox({
      name: 'Missouri',
      x: moved?.x ?? 0,
      y: moved?.y ?? 0,
      ...nameSize('Missouri'),
    });
    const apart =
      box.x1 <= button.x0 || box.x0 >= button.x1 || box.y1 <= button.y0 || box.y0 >= button.y1;
    expect(apart).toBe(true);
    expect(stateAt(region, moved?.x ?? 0, moved?.y ?? 0)).toBe('Missouri');
    // A state wholly under a control is not named.
    const all: ScreenRect = { x0: 0, y0: 0, x1: SCREEN.width, y1: SCREEN.height };
    expect(spots(region, { blocked: [all] })).toEqual([]);
  });
});

describe('the bundled names kept', () => {
  const name = (label: string, x: number, y: number): SetName => ({
    name: label,
    x,
    y,
    width: 60,
    height: 12,
  });

  it('are the ones whole in the frame, in their order', () => {
    const kept = keptNames(
      [
        name('Kansas', 200, 400),
        // Its top runs over the frame's: under the search field.
        name('Iowa', 200, FRAME.y0 + 2),
        name('Texas', 200, 700),
        // Off the frame's right side.
        name('Arkansas', FRAME.x1 - 10, 600),
      ],
      FRAME,
      6,
    );
    expect(kept.map((kept) => kept.name)).toEqual(['Kansas', 'Texas']);
  });

  it('leave out one that would meet one kept before it, or a control', () => {
    const kept = keptNames(
      [name('Kansas', 200, 400), name('Missouri', 200, 414), name('Oklahoma', 300, 600)],
      FRAME,
      6,
      [{ x0: 290, y0: 590, x1: 340, y1: 640 }],
    );
    expect(kept.map((kept) => kept.name)).toEqual(['Kansas']);
    // Clear by the gap, both are kept.
    const apart = keptNames([name('Kansas', 200, 400), name('Missouri', 200, 419)], FRAME, 6);
    expect(apart.map((kept) => kept.name)).toEqual(['Kansas', 'Missouri']);
  });
});

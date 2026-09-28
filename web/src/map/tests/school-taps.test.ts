/**
 * A school opened from the map: which school a click or a tap means (the
 * nearest within a mouse's or a finger's reach, its name under the pointer,
 * a lit school from the glow's own data at any zoom), and which clicks open
 * one (a single click, once no second one follows; never a double click, a
 * pinch or a hand moving the map).
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BASEMAP_IDS } from '../basemap/ids';
import {
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
} from '../glow/mercator';
import {
  DOUBLE_TAP_MS,
  HIT_RADIUS,
  OPEN_AFTER_MS,
  POINTER_CLASS,
  attachSchoolTaps,
  hitRadius,
  nearestLit,
  nearestSchool,
  schoolAt,
} from '../school-taps';
import type { LitSpots, SchoolHit } from '../school-taps';

const PEMBROKE_HILL = { id: 'A1902690', lon: -94.593001, lat: 39.03606 };
const BORDER_STAR = { id: '291640000557', lon: -94.592692, lat: 39.013304 };

function hit(id: string, distance: number): SchoolHit {
  return { id, name: id, lon: 0, lat: 0, distance };
}

/** A school the fake map draws: its dot, and its name in a box on the screen, if it has one. */
interface Drawn {
  readonly id: string;
  readonly name: string;
  readonly lon: number;
  readonly lat: number;
  /** [x0, y0, x1, y1] in CSS pixels. */
  readonly label?: readonly [number, number, number, number];
}

type Listener = (event: never) => void;
type Pixel = [number, number];

function isPoint(geometry: Pixel | [Pixel, Pixel]): geometry is Pixel {
  return typeof geometry[0] === 'number';
}

/**
 * As much of a MapLibre map as the taps use: an 800 by 600 view, never
 * tilted or turned, its school layers' dots and names, and its events.
 */
class FakeMap {
  readonly container = document.createElement('div');
  readonly listeners = new Map<string, Set<Listener>>();
  layers = new Set<string>([BASEMAP_IDS.schoolDots, BASEMAP_IDS.schoolNames]);
  drawn: Drawn[] = [];
  zoom = 14;
  center = { x: mercatorXFromLng(PEMBROKE_HILL.lon), y: mercatorYFromLat(PEMBROKE_HILL.lat) };
  readonly width = 800;
  readonly height = 600;

  get scale(): number {
    return 512 * 2 ** this.zoom;
  }
  on(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }
  off(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }
  fire(type: string, event: object): void {
    for (const listener of this.listeners.get(type) ?? []) (listener as (e: object) => void)(event);
  }
  getCanvasContainer(): HTMLElement {
    return this.container;
  }
  getLayer(id: string): object | undefined {
    return this.layers.has(id) ? {} : undefined;
  }
  getZoom(): number {
    return this.zoom;
  }
  project([lon, lat]: [number, number]): { x: number; y: number } {
    return {
      x: (mercatorXFromLng(lon) - this.center.x) * this.scale + this.width / 2,
      y: (mercatorYFromLat(lat) - this.center.y) * this.scale + this.height / 2,
    };
  }
  unproject([x, y]: [number, number]): { lng: number; lat: number } {
    return {
      lng: lngFromMercatorX(this.center.x + (x - this.width / 2) / this.scale),
      lat: latFromMercatorY(this.center.y + (y - this.height / 2) / this.scale),
    };
  }
  /** Dots whose circle (3 px) meets the query, names whose box does: MapLibre's own rule. */
  queryRenderedFeatures(geometry: Pixel | [Pixel, Pixel], options: { layers: string[] }): object[] {
    const [[x0, y0], [x1, y1]] = isPoint(geometry) ? [geometry, geometry] : geometry;
    const features: object[] = [];
    for (const school of this.drawn) {
      const properties = { id: school.id, name: school.name };
      const point = { type: 'Point', coordinates: [school.lon, school.lat] };
      const { x, y } = this.project([school.lon, school.lat]);
      const dx = Math.max(x0 - x, 0, x - x1);
      const dy = Math.max(y0 - y, 0, y - y1);
      if (options.layers.includes(BASEMAP_IDS.schoolDots) && Math.hypot(dx, dy) <= 3) {
        features.push({ layer: { id: BASEMAP_IDS.schoolDots }, properties, geometry: point });
      }
      const box = school.label;
      if (
        box !== undefined &&
        options.layers.includes(BASEMAP_IDS.schoolNames) &&
        box[0] <= x1 &&
        box[2] >= x0 &&
        box[1] <= y1 &&
        box[3] >= y0
      ) {
        features.push({ layer: { id: BASEMAP_IDS.schoolNames }, properties, geometry: point });
      }
    }
    return features;
  }
  get map(): MapLibreMap {
    return this as unknown as MapLibreMap;
  }
}

/** The glow's data for these schools, as data/closings.ts lightSchools gives it. */
function lit(
  schools: readonly { id: string; lon: number; lat: number }[],
  names?: string[],
): LitSpots {
  return {
    lngLat: new Float64Array(schools.flatMap((school) => [school.lon, school.lat])),
    ids: schools.map((school) => school.id),
    names: names ?? schools.map((school) => school.id),
  };
}

/** The place `dx`, `dy` CSS pixels from a school on the fake map. */
function beside(map: FakeMap, school: { lon: number; lat: number }, dx: number, dy: number) {
  const at = map.project([school.lon, school.lat]);
  return { x: at.x + dx, y: at.y + dy };
}

describe('the hit radius', () => {
  it('is a mouse’s or a pen’s, and wider for a finger', () => {
    expect(hitRadius('mouse')).toBe(HIT_RADIUS.mouse);
    expect(hitRadius('pen')).toBe(HIT_RADIUS.mouse);
    expect(hitRadius('')).toBe(HIT_RADIUS.mouse);
    expect(hitRadius('touch')).toBe(HIT_RADIUS.touch);
    expect(HIT_RADIUS.mouse).toBeCloseTo(6, 0);
    expect(HIT_RADIUS.touch).toBeCloseTo(16, 0);
  });
});

describe('the school meant', () => {
  it('is the nearest within the radius', () => {
    expect(nearestSchool([hit('far', 5), hit('near', 2), hit('farther', 12)], 6)?.id).toBe('near');
    // The edge of the radius is in it.
    expect(nearestSchool([hit('edge', 6)], 6)?.id).toBe('edge');
  });

  it('is none when none is within the radius', () => {
    expect(nearestSchool([hit('out', 6.01), hit('further', 30)], 6)).toBeNull();
    expect(nearestSchool([], 16)).toBeNull();
    expect(nearestSchool([hit('broken', Number.NaN)], 16)).toBeNull();
  });
});

describe('a lit school', () => {
  const map = new FakeMap();

  it('is found from the glow’s data, the nearest within the radius, named as the map names it', () => {
    const spots = lit(
      [PEMBROKE_HILL, BORDER_STAR],
      ['THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS', 'BORDER STAR MONTESSORI'],
    );
    const pointer = (x: number, y: number) => {
      const at = map.unproject([map.width / 2 + x, map.height / 2 + y]);
      return { x: mercatorXFromLng(at.lng), y: mercatorYFromLat(at.lat) };
    };
    const hit = nearestLit(spots, pointer(3, -4), map.scale, HIT_RADIUS.mouse);
    expect(hit).toMatchObject({
      id: PEMBROKE_HILL.id,
      name: 'The Pembroke Hill School - Wornall Campus',
      lon: PEMBROKE_HILL.lon,
      lat: PEMBROKE_HILL.lat,
    });
    expect(hit?.distance).toBeCloseTo(5, 6);
    // Just out of a mouse's reach, and in a finger's.
    expect(nearestLit(spots, pointer(6, -4), map.scale, HIT_RADIUS.mouse)).toBeNull();
    expect(nearestLit(spots, pointer(6, -4), map.scale, HIT_RADIUS.touch)?.id).toBe(
      PEMBROKE_HILL.id,
    );
    expect(nearestLit(lit([]), pointer(0, 0), map.scale, HIT_RADIUS.touch)).toBeNull();
  });

  it('takes a tap at the national view, where its light is small, and the nearer of two lights', () => {
    map.zoom = 4;
    map.layers = new Set();
    const spots = lit([PEMBROKE_HILL, BORDER_STAR]);
    // The two are under a pixel apart here: the one nearer the pointer is meant.
    const below = beside(map, BORDER_STAR, 0, 3);
    expect(schoolAt(map.map, below, HIT_RADIUS.mouse, spots)?.id).toBe(BORDER_STAR.id);
    const above = beside(map, PEMBROKE_HILL, 0, -3);
    expect(schoolAt(map.map, above, HIT_RADIUS.mouse, spots)?.id).toBe(PEMBROKE_HILL.id);
    expect(
      schoolAt(map.map, beside(map, PEMBROKE_HILL, 0, 30), HIT_RADIUS.touch, spots),
    ).toBeNull();
    // Nothing lit, nothing to find.
    expect(schoolAt(map.map, above, HIT_RADIUS.touch, null)).toBeNull();
    expect(schoolAt(map.map, above, HIT_RADIUS.touch, lit([]))).toBeNull();
  });
});

describe('a drawn school', () => {
  let map: FakeMap;
  beforeEach(() => {
    map = new FakeMap();
    map.drawn = [
      { ...PEMBROKE_HILL, name: 'The Pembroke Hill School - Wornall Campus' },
      {
        id: '290000000001',
        name: 'Next Door',
        lon: PEMBROKE_HILL.lon + 0.0004,
        lat: PEMBROKE_HILL.lat,
      },
    ];
  });

  it('is its dot nearest the pointer, within a mouse’s reach', () => {
    const next = map.drawn[1];
    if (next === undefined) throw new Error('no school');
    // About 9 px apart at zoom 14: a pointer 2 px off each finds each.
    expect(
      schoolAt(map.map, beside(map, PEMBROKE_HILL, 2, 1), HIT_RADIUS.mouse, null),
    ).toMatchObject({
      id: PEMBROKE_HILL.id,
      name: 'The Pembroke Hill School - Wornall Campus',
    });
    expect(schoolAt(map.map, beside(map, next, -2, 1), HIT_RADIUS.mouse, null)?.id).toBe(next.id);
    expect(schoolAt(map.map, beside(map, PEMBROKE_HILL, -9, 0), HIT_RADIUS.mouse, null)).toBeNull();
  });

  it('is found a finger’s width off, where a mouse would miss it', () => {
    const off = beside(map, PEMBROKE_HILL, -8, 10);
    expect(schoolAt(map.map, off, HIT_RADIUS.mouse, null)).toBeNull();
    expect(schoolAt(map.map, off, HIT_RADIUS.touch, null)?.id).toBe(PEMBROKE_HILL.id);
    expect(
      schoolAt(map.map, beside(map, PEMBROKE_HILL, -20, 12), HIT_RADIUS.touch, null),
    ).toBeNull();
  });

  it('is the one whose name is under the pointer, before a dot beside it', () => {
    const next = map.drawn[1];
    if (next === undefined) throw new Error('no school');
    const at = map.project([next.lon, next.lat]);
    // Pembroke Hill's name, set just past its neighbour's dot.
    map.drawn = [
      {
        ...PEMBROKE_HILL,
        name: 'Pembroke Hill',
        label: [at.x + 6, at.y - 8, at.x + 120, at.y + 8],
      },
      next,
    ];
    const meant = (x: number, y: number, radius: number): string | undefined =>
      schoolAt(map.map, { x: at.x + x, y: at.y + y }, radius, null)?.id;
    // On the name, far from its dot: that school, with a mouse or a finger.
    expect(meant(60, 0, HIT_RADIUS.mouse)).toBe(PEMBROKE_HILL.id);
    // On the name, a finger's width from the other school's dot: still the name's.
    expect(meant(10, 0, HIT_RADIUS.touch)).toBe(PEMBROKE_HILL.id);
    // A name only beside the pointer counts at the radius's edge: a dot nearer wins,
    expect(meant(2, 0, HIT_RADIUS.touch)).toBe(next.id);
    // and with none near, the name does.
    expect(meant(60, 16, HIT_RADIUS.touch)).toBe(PEMBROKE_HILL.id);
    expect(meant(60, 16, HIT_RADIUS.mouse)).toBeUndefined();
  });

  it('and a lit one are one school: the nearest of all is meant', () => {
    // A light about 6 px west of Pembroke Hill's dot.
    const spots = lit([
      { ...BORDER_STAR, lon: PEMBROKE_HILL.lon - 0.00026, lat: PEMBROKE_HILL.lat },
    ]);
    const pointer = beside(map, PEMBROKE_HILL, -4, 0);
    expect(schoolAt(map.map, pointer, HIT_RADIUS.mouse, spots)?.id).toBe(BORDER_STAR.id);
    expect(schoolAt(map.map, beside(map, PEMBROKE_HILL, -1, 0), HIT_RADIUS.mouse, spots)?.id).toBe(
      PEMBROKE_HILL.id,
    );
  });

  it('is none where the map draws no school layers', () => {
    map.layers = new Set();
    expect(schoolAt(map.map, beside(map, PEMBROKE_HILL, 0, 0), HIT_RADIUS.touch, null)).toBeNull();
  });
});

describe('a click on the map', () => {
  let map: FakeMap;
  let opened: string[];
  let stop: () => void;
  let now: number;

  /** A click at `point`, `after` ms after the last event, as MapLibre fires it after its press. */
  const click = (
    point: { x: number; y: number },
    after = 1000,
    pointerType = 'mouse',
    detail = 1,
  ) => {
    now += after;
    const originalEvent = { timeStamp: now, detail, pointerType, buttons: 0 };
    map.fire('mousedown', { point, originalEvent });
    map.fire('click', { point, originalEvent });
  };
  const dblclick = (point: { x: number; y: number }) => {
    const event = {
      point,
      originalEvent: { timeStamp: now, detail: 2 },
      prevented: false,
      preventDefault() {
        event.prevented = true;
      },
    };
    map.fire('dblclick', event);
    return event.prevented;
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame'] });
    map = new FakeMap();
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    opened = [];
    now = 0;
    stop = attachSchoolTaps(map.map, {
      lit: () => null,
      onSchool: (school) => opened.push(school.id),
    });
  });

  afterEach(() => {
    stop();
    vi.useRealTimers();
  });

  it('on a school opens it, once no second click follows', () => {
    click(beside(map, PEMBROKE_HILL, 1, 1));
    vi.advanceTimersByTime(OPEN_AFTER_MS - 1);
    expect(opened).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
  });

  it('on no school opens nothing', () => {
    click(beside(map, PEMBROKE_HILL, 40, 0));
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([]);
  });

  it('reaches as far as its pointer does: a finger further than a mouse', () => {
    click(beside(map, PEMBROKE_HILL, 10, 6), 1000, 'mouse');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([]);
    click(beside(map, PEMBROKE_HILL, 10, 6), 1000, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
  });

  it('reads a click with no pointer type by the last press on the map', () => {
    map.container.dispatchEvent(Object.assign(new Event('pointerdown'), { pointerType: 'touch' }));
    click(beside(map, PEMBROKE_HILL, 10, 6), 1000, '');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
  });

  it('twice, a double click, opens nothing: the map zooms in', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    click(at);
    click(at, 150);
    expect(dblclick(at)).toBe(false);
    vi.advanceTimersByTime(DOUBLE_TAP_MS * 2);
    expect(opened).toEqual([]);
    // A double tap too, though its second click names no double.
    click(at, 1000, 'touch');
    click(at, 250, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS * 2);
    expect(opened).toEqual([]);
  });

  it('whose second comes after the school opened keeps the pick’s flight: the map does not zoom', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    click(at);
    vi.advanceTimersByTime(OPEN_AFTER_MS);
    click(at, 400, 'mouse', 2);
    expect(dblclick(at)).toBe(true);
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
    // Long after, a click is a click again.
    click(at, 2000);
    vi.advanceTimersByTime(OPEN_AFTER_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id, PEMBROKE_HILL.id]);
  });

  it('is let go when the map is moved by hand, pressed again, or turned by a wheel before it opens', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    for (const type of ['movestart', 'mousedown', 'wheel', 'touchstart']) {
      click(at);
      const originalEvent = { timeStamp: now + 100, touches: [{}] };
      map.fire(type, { point: { x: 700, y: 50 }, originalEvent });
      vi.advanceTimersByTime(DOUBLE_TAP_MS);
      expect(opened, type).toEqual([]);
    }
    // The map's own moves (a flight) leave it be.
    click(at);
    map.fire('movestart', {});
    vi.advanceTimersByTime(OPEN_AFTER_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
  });

  it('heard after a press that came after it opens nothing: a busy page’s late click', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    // A double tap whose first click comes after the second touch.
    map.fire('touchstart', { point: at, originalEvent: { touches: [{}], timeStamp: now + 150 } });
    click(at, 50, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([]);
  });

  it('while two fingers are on the map opens nothing', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    map.fire('touchstart', { point: at, originalEvent: { touches: [{}, {}], timeStamp: now } });
    click(at, 50, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([]);
    map.fire('touchend', { originalEvent: { touches: [] } });
    click(at, 1000, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([PEMBROKE_HILL.id]);
  });

  it('opens nothing once the taps are stopped', () => {
    click(beside(map, PEMBROKE_HILL, 0, 0));
    stop();
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(opened).toEqual([]);
  });
});

describe('the cursor', () => {
  let map: FakeMap;
  let looks: number;
  let stop: () => void;
  const move = (point: { x: number; y: number }, buttons = 0) => {
    map.fire('mousemove', { point, originalEvent: { buttons } });
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame'] });
    map = new FakeMap();
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    looks = 0;
    stop = attachSchoolTaps(map.map, {
      lit: () => {
        looks += 1;
        return null;
      },
      onSchool: () => undefined,
    });
  });

  afterEach(() => {
    stop();
    vi.useRealTimers();
  });

  it('is a pointer over a school and the map’s own elsewhere, looked for once a frame', () => {
    const pointer = (): boolean => map.container.classList.contains(POINTER_CLASS);
    for (let dx = 20; dx >= 0; dx -= 2) move(beside(map, PEMBROKE_HILL, dx, 0));
    expect(pointer()).toBe(false);
    vi.advanceTimersToNextFrame();
    expect(looks).toBe(1);
    expect(pointer()).toBe(true);
    move(beside(map, PEMBROKE_HILL, 30, 0));
    vi.advanceTimersToNextFrame();
    expect(pointer()).toBe(false);
    // Dragging, it is the map's; off the map, it is gone.
    move(beside(map, PEMBROKE_HILL, 0, 0));
    vi.advanceTimersToNextFrame();
    expect(pointer()).toBe(true);
    move(beside(map, PEMBROKE_HILL, 0, 0), 1);
    expect(pointer()).toBe(false);
    move(beside(map, PEMBROKE_HILL, 0, 0));
    vi.advanceTimersToNextFrame();
    map.fire('mouseout', {});
    expect(pointer()).toBe(false);
    move(beside(map, PEMBROKE_HILL, 0, 0));
    vi.advanceTimersToNextFrame();
    stop();
    expect(pointer()).toBe(false);
  });
});

// @vitest-environment node
/**
 * A school opened from the map: which schools a click or a tap reaches (a
 * mark's edge within a mouse's or a finger's reach, while the mark is drawn;
 * a name under the pointer; a lit school from the glow's own data at any
 * zoom; a speck of dust from the glow's own data further out), what it does
 * with them (opens the one it means, or zooms in toward several), and when (a
 * mouse's click at once, a finger's tap once no second tap follows; never a
 * double tap, a pinch or a hand moving the map).
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { BASEMAP_IDS, SCHOOL_LIT_STATE } from '../basemap/ids';
import {
  SCHOOL_DOT_OPACITY,
  SCHOOL_DOT_RADIUS,
  SCHOOL_DUST_FROM,
  SCHOOL_DUST_UNTIL,
  dotAt,
} from '../basemap/dots';
import {
  SCHOOL_DOTS_FROM,
  SCHOOL_NAMES_FROM,
  SCHOOL_TILES_MIN_ZOOM,
  schoolDotOpacity,
  schoolDotRadius,
  schoolDustOpacity,
  schoolDustRadius,
} from '../basemap/schools';
import { dustStyle, litRadius } from '../glow-mount';
import { dustAtZoom } from '../glow/dust';
import {
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
} from '../glow/mercator';
import {
  DOUBLE_TAP_MS,
  DRILL_MARGIN,
  DRILL_STEP,
  DRILL_ZOOM,
  HIT_RADIUS,
  POINTER_CLASS,
  SHOWN_OPACITY,
  TAP_WAIT_MS,
  attachSchoolTaps,
  drillView,
  dustInReach,
  hitRadius,
  litInReach,
  meantSchool,
  schoolsInReach,
  tapAction,
} from '../school-taps';
import type {
  DustSpots,
  LitSpots,
  MarkHit,
  SchoolHit,
  SchoolTaps,
  TapAction,
} from '../school-taps';

const PEMBROKE_HILL = { id: 'A1902690', lon: -94.593001, lat: 39.03606 };
const BORDER_STAR = { id: '291640000557', lon: -94.592692, lat: 39.013304 };

/** A school the fake map draws: its dot, and its name in a box on the screen, if it has one. */
interface Drawn {
  readonly id: string;
  readonly name: string;
  readonly lon: number;
  readonly lat: number;
  /** [x0, y0, x1, y1] in CSS pixels. */
  readonly label?: readonly [number, number, number, number];
  /** Whether the glow lights it (its dot's feature state). */
  readonly lit?: boolean;
}

type Listener = (event: never) => void;
type Pixel = [number, number];

function isPoint(geometry: Pixel | [Pixel, Pixel]): geometry is Pixel {
  return typeof geometry[0] === 'number';
}

/** The map's canvas container, as far as the taps use it: its pointer events, and its classes. */
class FakeContainer extends EventTarget {
  private readonly classes = new Set<string>();
  readonly classList = {
    toggle: (name: string, on: boolean): void => {
      if (on) this.classes.add(name);
      else this.classes.delete(name);
    },
    contains: (name: string): boolean => this.classes.has(name),
  };
}

/** Animation frames, run as fake timers every 16 ms (this environment has no frames of its own). */
const FRAME_MS = 16;
function fakeFrames(): void {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  vi.stubGlobal('requestAnimationFrame', (callback: () => void) => setTimeout(callback, FRAME_MS));
  vi.stubGlobal('cancelAnimationFrame', (id: ReturnType<typeof setTimeout>) => {
    clearTimeout(id);
  });
}
function realFrames(): void {
  vi.unstubAllGlobals();
  vi.useRealTimers();
}
function nextFrame(): void {
  vi.advanceTimersByTime(FRAME_MS);
}

/** One of MapLibre's gesture handlers, as far as turning it off and on goes. */
function toggle(): { isEnabled(): boolean; enable(): void; disable(): void } {
  let enabled = true;
  return {
    isEnabled: () => enabled,
    enable: () => {
      enabled = true;
    },
    disable: () => {
      enabled = false;
    },
  };
}

/**
 * As much of a MapLibre map as the taps use: an 800 by 600 view, never
 * tilted or turned, as close as zoom 16, its school layers' dots and names,
 * and its events.
 */
class FakeMap {
  readonly container = new FakeContainer();
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
    return this.container as unknown as HTMLElement;
  }
  getContainer(): { clientWidth: number; clientHeight: number } {
    return { clientWidth: this.width, clientHeight: this.height };
  }
  getLayer(id: string): object | undefined {
    return this.layers.has(id) ? {} : undefined;
  }
  getZoom(): number {
    return this.zoom;
  }
  getMaxZoom(): number {
    return 16;
  }
  /** The map's own double click and double tap zoom, and its drag. */
  readonly doubleClickZoom = toggle();
  readonly dragPan = toggle();
  /** Whether the map is on its way somewhere (a flight). */
  moving = false;
  isMoving(): boolean {
    return this.moving;
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
  /** Dots whose circle meets the query, names whose box does: MapLibre's own rule. */
  queryRenderedFeatures(geometry: Pixel | [Pixel, Pixel], options: { layers: string[] }): object[] {
    const [[x0, y0], [x1, y1]] = isPoint(geometry) ? [geometry, geometry] : geometry;
    const features: object[] = [];
    for (const school of this.drawn) {
      const properties = { id: school.id, name: school.name };
      const point = { type: 'Point', coordinates: [school.lon, school.lat] };
      const state = school.lit === true ? { [SCHOOL_LIT_STATE]: true } : {};
      const { x, y } = this.project([school.lon, school.lat]);
      const dx = Math.max(x0 - x, 0, x - x1);
      const dy = Math.max(y0 - y, 0, y - y1);
      if (
        options.layers.includes(BASEMAP_IDS.schoolDots) &&
        Math.hypot(dx, dy) <= schoolDotRadius(this.zoom)
      ) {
        features.push({
          layer: { id: BASEMAP_IDS.schoolDots },
          properties,
          geometry: point,
          state,
        });
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
        features.push({
          layer: { id: BASEMAP_IDS.schoolNames },
          properties,
          geometry: point,
          state,
        });
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

/**
 * The glow's dust of these schools, as glow-mount.ts gives it: every one
 * drawn, found in a box around a point.
 */
function dust(
  schools: readonly { id: string; lon: number; lat: number }[],
  names?: string[],
): DustSpots {
  return {
    lngLat: new Float64Array(schools.flatMap((school) => [school.lon, school.lat])),
    ids: schools.map((school) => school.id),
    names: names ?? schools.map((school) => school.id),
    near: (x, y, reach) =>
      schools.flatMap((school, i) =>
        Math.abs(mercatorXFromLng(school.lon) - x) <= reach &&
        Math.abs(mercatorYFromLat(school.lat) - y) <= reach
          ? [i]
          : [],
      ),
  };
}

/** The place `dx`, `dy` CSS pixels from a school on the fake map. */
function beside(map: FakeMap, school: { lon: number; lat: number }, dx: number, dy: number) {
  const at = map.project([school.lon, school.lat]);
  return { x: at.x + dx, y: at.y + dy };
}

/** A school `px` CSS pixels east of Pembroke Hill on the fake map, at its zoom. */
function eastOf(map: FakeMap, id: string, px: number): Drawn {
  const at = map.unproject([map.width / 2 + px, map.height / 2]);
  return { id, name: id, lon: at.lng, lat: PEMBROKE_HILL.lat };
}

function mark(id: string, distance: number, dx = 0, dy = 0): MarkHit {
  return { id, lon: 0, lat: 0, dx, dy, distance, name: () => id };
}

function opened(action: TapAction | null): string | undefined {
  return action?.kind === 'open' ? action.school.id : undefined;
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

describe('the school a tap means', () => {
  it('is the one mark under the pointer, before any nearer in reach', () => {
    expect(meantSchool([mark('beside', 2), mark('under', 0)])?.id).toBe('under');
    expect(meantSchool([mark('only', 5)])?.id).toBe('only');
  });

  it('is none where it could be several, or none is in reach', () => {
    expect(meantSchool([mark('one', 2), mark('two', 5)])).toBeNull();
    expect(meantSchool([mark('one', 0), mark('two', 0), mark('three', 3)])).toBeNull();
    expect(meantSchool([])).toBeNull();
  });
});

describe('a lit school', () => {
  const map = new FakeMap();

  it('is found from the glow’s data, by its light’s edge, named as the map names it', () => {
    const spots = lit(
      [PEMBROKE_HILL, BORDER_STAR],
      ['THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS', 'BORDER STAR MONTESSORI'],
    );
    const pointer = (x: number, y: number) => {
      const at = map.unproject([map.width / 2 + x, map.height / 2 + y]);
      return { x: mercatorXFromLng(at.lng), y: mercatorYFromLat(at.lat) };
    };
    // 5 px from its center, its light 2 px across: 3 px from its edge.
    const [hit, ...others] = litInReach(spots, pointer(3, -4), map.scale, HIT_RADIUS.mouse, 2);
    expect(others).toEqual([]);
    expect(hit).toMatchObject({ id: PEMBROKE_HILL.id, lon: PEMBROKE_HILL.lon });
    expect(hit?.distance).toBeCloseTo(3, 6);
    expect(hit?.name()).toBe('The Pembroke Hill School - Wornall Campus');
    // Under the pointer inside its light, out of a mouse's reach, and in a finger's.
    expect(litInReach(spots, pointer(1, 1), map.scale, HIT_RADIUS.mouse, 2)[0]?.distance).toBe(0);
    expect(litInReach(spots, pointer(9, 0), map.scale, HIT_RADIUS.mouse, 2)).toEqual([]);
    expect(litInReach(spots, pointer(9, 0), map.scale, HIT_RADIUS.touch, 2)).toHaveLength(1);
    expect(litInReach(lit([]), pointer(0, 0), map.scale, HIT_RADIUS.touch, 2)).toEqual([]);
  });

  it('is its glyph up close, its bright core in a city, and its blend’s spread farther out', () => {
    expect(litRadius(14)).toBeGreaterThan(4);
    expect(litRadius(9)).toBeGreaterThan(1);
    expect(litRadius(9)).toBeLessThan(litRadius(14));
    // Where the blend carries a lone light, two of its standard deviations: 2.4 px on a phone's
    // national view and 8 on a desktop's, as far as its light shows; then less as its core comes
    // in, under 7 px from zoom 5.5, where the wash around a crisp core is too faint to be its mark.
    expect(litRadius(2.12)).toBeCloseTo(2.4, 6);
    expect(litRadius(4)).toBeCloseTo(8, 6);
    for (let zoom = 2; zoom <= 5; zoom += 0.25) expect(litRadius(zoom)).toBeGreaterThanOrEqual(2.4);
    for (let zoom = 5.5; zoom <= 10; zoom += 0.25) expect(litRadius(zoom)).toBeLessThan(7);
    expect(litRadius(8)).toBeLessThan(3);
  });

  it('at zooms 4.5 to 6 takes a click across the light it shows, not across its faint wash', () => {
    // A lone light shows above 24 of 255 within about 7 to 9.5 px of its center at zooms 4.5 to 5,
    // on a light target of one or two pixels per CSS pixel alike…
    for (const zoom of [4.5, 4.75, 5]) {
      expect(litRadius(zoom)).toBeGreaterThan(6);
      expect(litRadius(zoom)).toBeLessThan(9.5);
      expect(litRadius(zoom) + HIT_RADIUS.mouse).toBeLessThan(16);
    }
    // …and within 4.5 px at 5.5 to 6, where its crisp core holds most of its light.
    for (const zoom of [5.5, 5.75, 6]) {
      expect(litRadius(zoom)).toBeGreaterThan(2.5);
      expect(litRadius(zoom)).toBeLessThan(4.5);
    }
  });

  it('two lights under a pixel apart at the national view: a tap zooms in toward them', () => {
    const national = new FakeMap();
    national.zoom = 4;
    national.layers = new Set();
    const spots = lit([PEMBROKE_HILL, BORDER_STAR]);
    const tap = beside(national, BORDER_STAR, 0, 3);
    const action = tapAction(national.map, tap, HIT_RADIUS.mouse, spots);
    if (action?.kind !== 'zoom') throw new Error(`zoomed no closer: ${JSON.stringify(action)}`);
    // To where a metro's schools stand apart, the two where they were on the screen.
    expect(action.view.zoom).toBe(DRILL_ZOOM);
    const before = national.project([BORDER_STAR.lon, BORDER_STAR.lat]);
    national.zoom = action.view.zoom;
    national.center = {
      x: mercatorXFromLng(action.view.lon),
      y: mercatorYFromLat(action.view.lat),
    };
    const middle = national.project([
      (BORDER_STAR.lon + PEMBROKE_HILL.lon) / 2,
      (BORDER_STAR.lat + PEMBROKE_HILL.lat) / 2,
    ]);
    expect(Math.hypot(middle.x - before.x, middle.y - before.y)).toBeLessThan(1);
    // There, the two are tens of pixels apart: a tap on one opens it.
    const star = national.project([BORDER_STAR.lon, BORDER_STAR.lat]);
    const hill = national.project([PEMBROKE_HILL.lon, PEMBROKE_HILL.lat]);
    expect(Math.hypot(star.x - hill.x, star.y - hill.y)).toBeGreaterThan(30);
    expect(opened(tapAction(national.map, star, HIT_RADIUS.touch, spots))).toBe(BORDER_STAR.id);
    expect(opened(tapAction(national.map, hill, HIT_RADIUS.touch, spots))).toBe(PEMBROKE_HILL.id);
  });

  it('alone in reach at the national view opens at once; far from any, nothing', () => {
    const national = new FakeMap();
    national.zoom = 4;
    national.layers = new Set();
    const spots = lit([BORDER_STAR]);
    const near = beside(national, BORDER_STAR, 0, 4);
    const action = tapAction(national.map, near, HIT_RADIUS.mouse, spots);
    expect(action).toEqual({
      kind: 'open',
      school: {
        id: BORDER_STAR.id,
        name: BORDER_STAR.id,
        lon: BORDER_STAR.lon,
        lat: BORDER_STAR.lat,
      },
    });
    expect(tapAction(national.map, beside(national, BORDER_STAR, 0, 40), 16, spots)).toBeNull();
    expect(tapAction(national.map, near, HIT_RADIUS.touch, null)).toBeNull();
  });
});

describe('a drawn school', () => {
  let map: FakeMap;
  beforeEach(() => {
    map = new FakeMap();
    map.drawn = [
      { ...PEMBROKE_HILL, name: 'The Pembroke Hill School - Wornall Campus' },
      eastOf(map, '290000000001', 30),
    ];
  });

  it('is its dot within a mouse’s reach of its edge, named as the map names it', () => {
    const edge = schoolDotRadius(map.zoom);
    const action = tapAction(map.map, beside(map, PEMBROKE_HILL, edge + 5, 0), 6, null);
    expect(action).toMatchObject({
      kind: 'open',
      school: { id: PEMBROKE_HILL.id, name: 'The Pembroke Hill School - Wornall Campus' },
    });
    expect(tapAction(map.map, beside(map, PEMBROKE_HILL, -(edge + 7), 0), 6, null)).toBeNull();
    // A finger reaches further.
    const off = beside(map, PEMBROKE_HILL, -(edge + 12), 0);
    expect(tapAction(map.map, off, HIT_RADIUS.mouse, null)).toBeNull();
    expect(opened(tapAction(map.map, off, HIT_RADIUS.touch, null))).toBe(PEMBROKE_HILL.id);
  });

  it('under the pointer is meant, though another’s dot is in a finger’s reach', () => {
    const next = map.drawn[1];
    if (next === undefined) throw new Error('no school');
    // Two dots 12 px apart, 5 px across each: the pointer on the edge of one, 7 px from the other.
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }, eastOf(map, next.id, 12)];
    const edge = schoolDotRadius(map.zoom);
    const onEdge = beside(map, PEMBROKE_HILL, edge - 0.2, 0);
    const marks = schoolsInReach(map.map, onEdge, HIT_RADIUS.touch, null);
    expect(marks.map((hit) => hit.id).sort()).toEqual([next.id, PEMBROKE_HILL.id].sort());
    expect(opened(tapAction(map.map, onEdge, HIT_RADIUS.touch, null))).toBe(PEMBROKE_HILL.id);
    // Between the two, on neither: it could be either, and the map zooms in.
    const between = beside(map, PEMBROKE_HILL, 6, 0);
    expect(tapAction(map.map, between, HIT_RADIUS.touch, null)?.kind).toBe('zoom');
  });

  it('under the pointer is meant before a mark whose center is nearer', () => {
    // At zoom 11 a lit school's glyph is wider than a dot: the pointer inside the glyph, just
    // outside the dot, nearer the dot's center than the glyph's.
    map.zoom = 11;
    const [glyph, dot] = [litRadius(11), schoolDotRadius(11)];
    expect(glyph).toBeGreaterThan(dot + 0.4);
    const gap = glyph + dot + 0.1;
    const neighbour = eastOf(map, '290000000001', gap);
    map.drawn = [neighbour];
    const pointer = beside(map, PEMBROKE_HILL, glyph - 0.1, 0);
    const toDot = Math.hypot(pointer.x - map.project([neighbour.lon, neighbour.lat]).x, 0);
    expect(toDot).toBeLessThan(glyph - 0.1);
    const spots = lit([PEMBROKE_HILL]);
    expect(opened(tapAction(map.map, pointer, HIT_RADIUS.mouse, spots))).toBe(PEMBROKE_HILL.id);
  });

  it('is found by its name under the pointer, and only under it', () => {
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
      opened(tapAction(map.map, { x: at.x + x, y: at.y + y }, radius, null));
    // On the name, far from its dot: that school, with a mouse or a finger.
    expect(meant(60, 0, HIT_RADIUS.mouse)).toBe(PEMBROKE_HILL.id);
    // On the name, a finger's reach from the other school's dot: the name is under the pointer.
    expect(meant(10, 0, HIT_RADIUS.touch)).toBe(PEMBROKE_HILL.id);
    // Just off the name: nothing, the name is no mark to reach for.
    expect(meant(60, 16, HIT_RADIUS.touch)).toBeUndefined();
  });

  it('lit by the glow is its light, not its hidden dot', () => {
    // A lit school's dot is not drawn: only its light, found from the glow's data, takes the tap.
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill', lit: true }];
    const on = beside(map, PEMBROKE_HILL, 0, 0);
    expect(schoolsInReach(map.map, on, HIT_RADIUS.mouse, null)).toEqual([]);
    const spots = lit([PEMBROKE_HILL], ['PEMBROKE HILL']);
    const marks = schoolsInReach(map.map, on, HIT_RADIUS.mouse, spots);
    expect(marks).toHaveLength(1);
    expect(marks[0]?.name()).toBe('Pembroke Hill');
  });

  it('and its light are one school: each school is counted once, by its nearest mark', () => {
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    const spots = lit([PEMBROKE_HILL]);
    const marks = schoolsInReach(map.map, beside(map, PEMBROKE_HILL, 2, 0), 16, spots);
    expect(marks.map((hit) => hit.id)).toEqual([PEMBROKE_HILL.id]);
    expect(marks[0]?.distance).toBe(0);
  });

  it('takes a tap only while its dot is drawn, as schools.ts draws it', () => {
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    map.layers = new Set([BASEMAP_IDS.schoolDots]);
    const on = (): { x: number; y: number } => beside(map, PEMBROKE_HILL, 0, 0);
    // None below the tiles' first zoom, where the dust stands for the dots; from it, dimmed as the
    // dust is there and taking taps, and whole across a metro.
    map.zoom = SCHOOL_TILES_MIN_ZOOM - 0.02;
    expect(schoolDotOpacity(map.zoom)).toBe(0);
    expect(tapAction(map.map, on(), HIT_RADIUS.touch, null)).toBeNull();
    map.zoom = SCHOOL_TILES_MIN_ZOOM;
    expect(schoolDotOpacity(map.zoom)).toBeGreaterThanOrEqual(SHOWN_OPACITY);
    expect(opened(tapAction(map.map, on(), HIT_RADIUS.touch, null))).toBe(PEMBROKE_HILL.id);
    map.zoom = SCHOOL_DOTS_FROM;
    expect(opened(tapAction(map.map, on(), HIT_RADIUS.touch, null))).toBe(PEMBROKE_HILL.id);
    // Names take taps once drawn too, and a map without the school layers takes none.
    expect(SCHOOL_NAMES_FROM).toBeGreaterThan(SCHOOL_DOTS_FROM);
    map.layers = new Set();
    expect(tapAction(map.map, on(), HIT_RADIUS.touch, null)).toBeNull();
  });

  it('where no zoom tells two apart, the nearest opens', () => {
    // Two schools at one place: one campus.
    map.drawn = [
      { ...PEMBROKE_HILL, name: 'Pembroke Hill' },
      { ...PEMBROKE_HILL, id: '290000000002', name: 'Pembroke Hill Upper' },
    ];
    const action = tapAction(map.map, beside(map, PEMBROKE_HILL, 1, 0), HIT_RADIUS.touch, null);
    expect(action?.kind).toBe('open');
    // As close as the map goes, two apart open the nearest too.
    map.zoom = 16;
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }, eastOf(map, '290000000003', 20)];
    const tap = beside(map, PEMBROKE_HILL, 8, 0);
    expect(opened(tapAction(map.map, tap, HIT_RADIUS.touch, null))).toBe(PEMBROKE_HILL.id);
  });
});

describe('a school drawn as dust', () => {
  const map = new FakeMap();
  beforeEach(() => {
    map.zoom = 8;
    map.drawn = [];
    map.layers = new Set([BASEMAP_IDS.schoolDots, BASEMAP_IDS.schoolNames]);
  });

  it('is found from the glow’s dust, by its speck’s edge, named as the map names it', () => {
    const specks = dust([PEMBROKE_HILL], ['THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS']);
    const pointer = (x: number, y: number) => {
      const at = map.unproject([map.width / 2 + x, map.height / 2 + y]);
      return { x: mercatorXFromLng(at.lng), y: mercatorYFromLat(at.lat) };
    };
    // 5 px from its center, the speck 1 px across: 4 px from its edge.
    const [hit, ...others] = dustInReach(specks, pointer(3, -4), map.scale, HIT_RADIUS.mouse, 1);
    expect(others).toEqual([]);
    expect(hit).toMatchObject({ id: PEMBROKE_HILL.id, lon: PEMBROKE_HILL.lon });
    expect(hit?.distance).toBeCloseTo(4, 6);
    expect(hit?.name()).toBe('The Pembroke Hill School - Wornall Campus');
    expect(dustInReach(specks, pointer(9, 0), map.scale, HIT_RADIUS.mouse, 1)).toEqual([]);
    expect(dustInReach(specks, pointer(9, 0), map.scale, HIT_RADIUS.touch, 1)).toHaveLength(1);
  });

  it('alone in reach opens at once, as its dot would; far from any, nothing', () => {
    const specks = dust([PEMBROKE_HILL]);
    const tap = (dx: number, radius: number) =>
      tapAction(map.map, beside(map, PEMBROKE_HILL, dx, 0), radius, null, undefined, specks);
    expect(opened(tap(2, HIT_RADIUS.mouse))).toBe(PEMBROKE_HILL.id);
    expect(opened(tap(12, HIT_RADIUS.touch))).toBe(PEMBROKE_HILL.id);
    expect(tap(12, HIT_RADIUS.mouse)).toBeNull();
    // With no dust, nothing is there.
    expect(tapAction(map.map, beside(map, PEMBROKE_HILL, 2, 0), HIT_RADIUS.touch, null)).toBeNull();
  });

  it('beside another in a finger’s reach opens neither: the map zooms in toward both', () => {
    // Pembroke Hill and Border Star, 2.5 km apart: about 10 px at zoom 8.
    const specks = dust([PEMBROKE_HILL, BORDER_STAR]);
    const between = beside(map, PEMBROKE_HILL, 0, 2);
    const action = tapAction(map.map, between, HIT_RADIUS.touch, null, undefined, specks);
    if (action?.kind !== 'zoom') throw new Error(`opened: ${JSON.stringify(action)}`);
    expect(action.view.zoom).toBeGreaterThanOrEqual(8 + DRILL_STEP);
    expect(action.view.zoom).toBeLessThanOrEqual(DRILL_ZOOM);
    // With a mouse right on one, that one.
    const on = beside(map, BORDER_STAR, 0, 0);
    expect(opened(tapAction(map.map, on, HIT_RADIUS.mouse, null, undefined, specks))).toBe(
      BORDER_STAR.id,
    );
  });

  it('takes a tap only while its speck is drawn, as schools.ts says the glow draws it', () => {
    const specks = dust([PEMBROKE_HILL]);
    // A finger 2 px off its edge: in reach wherever the speck takes taps.
    const tap = () =>
      tapAction(
        map.map,
        beside(map, PEMBROKE_HILL, schoolDustRadius(map.zoom) + 2, 0),
        HIT_RADIUS.touch,
        null,
        undefined,
        specks,
      );
    map.layers = new Set();
    for (let zoom = SCHOOL_DUST_FROM - 0.5; zoom <= SCHOOL_DUST_UNTIL + 0.5; zoom += 0.01) {
      map.zoom = zoom;
      const where = `zoom ${zoom.toFixed(2)}`;
      // The glow layer's own speck: its opacity and radius are the helpers'.
      const drawn = dustAtZoom(dustStyle(), zoom);
      expect(schoolDustOpacity(zoom), where).toBeCloseTo(drawn?.opacity ?? 0, 9);
      if (drawn !== null) expect(schoolDustRadius(zoom), where).toBeCloseTo(drawn.radius, 9);
      // A tap finds it exactly where it is at least half drawn, as a dot.
      expect(tap() !== null, where).toBe((drawn?.opacity ?? 0) >= SHOWN_OPACITY);
    }
    // Faint across a state, it takes none; from about zoom 7.9 it does, until the dots draw alone.
    map.zoom = 7.5;
    expect(schoolDustOpacity(map.zoom)).toBeGreaterThan(0);
    expect(tap()).toBeNull();
    map.zoom = 8;
    expect(opened(tap())).toBe(PEMBROKE_HILL.id);
    map.zoom = SCHOOL_DUST_UNTIL;
    expect(schoolDustOpacity(map.zoom)).toBe(0);
    expect(tap()).toBeNull();
    expect(schoolDustRadius(8)).toBe(dotAt(SCHOOL_DOT_RADIUS, 8));
    expect(schoolDustOpacity(8)).toBe(dotAt(SCHOOL_DOT_OPACITY, 8));
  });

  it('and its dot, where both are drawn, are one school', () => {
    map.zoom = 9.5;
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    const specks = dust([PEMBROKE_HILL]);
    const marks = schoolsInReach(map.map, beside(map, PEMBROKE_HILL, 1, 0), 16, null, specks);
    expect(marks.map((hit) => hit.id)).toEqual([PEMBROKE_HILL.id]);
    expect(
      opened(tapAction(map.map, beside(map, PEMBROKE_HILL, 1, 0), 16, null, undefined, specks)),
    ).toBe(PEMBROKE_HILL.id);
  });
});

describe('a tap on several schools', () => {
  const map = new FakeMap();
  const tap = { x: 400, y: 300 };
  /** The whole 800 by 600 map. */
  const whole = { left: 0, top: 0, right: 800, bottom: 600 };
  /** What a panel beside the map leaves of it, under a search strip 64 px high. */
  const open = { left: 388, top: 64, right: 800, bottom: 600 };

  it('zooms in as far as keeps them in the area, to DRILL_ZOOM at most', () => {
    map.zoom = 5;
    // Four pixels apart: room to spread 176 times, past DRILL_ZOOM, so as far as DRILL_ZOOM.
    const close = [mark('a', 1, -2, 0), mark('b', 1, 2, 0)];
    expect(drillView(map.map, tap, close, whole)?.zoom).toBe(DRILL_ZOOM);
    // Far apart, they would leave the area past a smaller zoom in: no further than that.
    const wide = [mark('a', 1, -60, 0), mark('b', 1, 60, 0)];
    const room = (map.width / 2 - DRILL_MARGIN) / 60;
    expect(5 + Math.log2(room)).toBeGreaterThan(5 + DRILL_STEP);
    expect(drillView(map.map, tap, wide, whole)?.zoom).toBeCloseTo(5 + Math.log2(room), 6);
    // Where the panel leaves less of the map, less far.
    const middling = [mark('a', 1, -30, 0), mark('b', 1, 30, 0)];
    const inWhole = (map.width / 2 - DRILL_MARGIN) / 30;
    const inOpen = ((open.right - open.left) / 2 - DRILL_MARGIN) / 30;
    expect(5 + Math.log2(inOpen)).toBeGreaterThan(5 + DRILL_STEP);
    expect(drillView(map.map, tap, middling, whole)?.zoom).toBeCloseTo(5 + Math.log2(inWhole), 6);
    expect(drillView(map.map, tap, middling, open)?.zoom).toBeCloseTo(5 + Math.log2(inOpen), 6);
    // The tap a little off to one side of them changes nothing: their middle is what counts.
    const aside = { x: tap.x - 5, y: tap.y + 3 };
    const shifted = [mark('a', 1, -55, -3), mark('b', 1, 65, -3)];
    expect(drillView(map.map, aside, shifted, whole)?.zoom).toBeCloseTo(5 + Math.log2(room), 6);
  });

  it('zooms in by DRILL_STEP at least, and no closer than the map goes', () => {
    map.zoom = 12;
    const close = [mark('a', 1, -3, 0), mark('b', 1, 3, 0)];
    expect(drillView(map.map, tap, close, whole)?.zoom).toBe(12 + DRILL_STEP);
    // Spread wider than the area: still DRILL_STEP.
    const wide = [mark('a', 1, -300, 0), mark('b', 1, 300, 0)];
    expect(drillView(map.map, tap, wide, open)?.zoom).toBe(12 + DRILL_STEP);
    map.zoom = 15;
    expect(drillView(map.map, tap, close, whole)?.zoom).toBe(16);
    map.zoom = 16;
    expect(drillView(map.map, tap, close, whole)).toBeNull();
  });

  it('puts the middle of them in the middle of the area, clear of a panel and the search strip', () => {
    map.zoom = 6;
    const off = { x: 250, y: 420 };
    // Their middle: 4 px right of the tap and 2 px under it, under where a panel would be.
    const middle = { x: off.x + 4, y: off.y + 2 };
    const under = map.unproject([middle.x, middle.y]);
    const marks = [mark('a', 1, 2, 3), mark('b', 1, 6, 1)];
    const view = drillView(map.map, off, marks, open);
    if (view === null) throw new Error('no zoom');
    const scale = 512 * 2 ** view.zoom;
    const x = (mercatorXFromLng(under.lng) - mercatorXFromLng(view.lon)) * scale + map.width / 2;
    const y = (mercatorYFromLat(under.lat) - mercatorYFromLat(view.lat)) * scale + map.height / 2;
    expect(x).toBeCloseTo((open.left + open.right) / 2, 6);
    expect(y).toBeCloseTo((open.top + open.bottom) / 2, 6);
    // And each of them inside it, DRILL_MARGIN in.
    for (const { dx, dy } of marks) {
      const spread = 2 ** (view.zoom - map.zoom);
      const at = { x: x + (dx - 4) * spread, y: y + (dy - 2) * spread };
      expect(at.x).toBeGreaterThanOrEqual(open.left + DRILL_MARGIN - 1e-6);
      expect(at.x).toBeLessThanOrEqual(open.right - DRILL_MARGIN + 1e-6);
      expect(at.y).toBeGreaterThanOrEqual(open.top + DRILL_MARGIN - 1e-6);
      expect(at.y).toBeLessThanOrEqual(open.bottom - DRILL_MARGIN + 1e-6);
    }
  });
});

describe('a click on the map', () => {
  let map: FakeMap;
  let actions: string[];
  let pending: (string | null)[];
  let taps: SchoolTaps;
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
  const touchStart = (point: { x: number; y: number }, after = 100, fingers = 1) => {
    now += after;
    const touches = Array.from({ length: fingers }, () => ({}));
    map.fire('touchstart', { point, originalEvent: { timeStamp: now, touches } });
  };

  beforeEach(() => {
    fakeFrames();
    map = new FakeMap();
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    actions = [];
    pending = [];
    now = 0;
    taps = attachSchoolTaps(map.map, {
      lit: () => null,
      onSchool: (school: SchoolHit) => actions.push(`open ${school.id}`),
      onZoom: (view) => actions.push(`zoom ${String(view.zoom)}`),
      onPending: (school) => pending.push(school?.id ?? null),
    });
  });

  afterEach(() => {
    taps.stop();
    realFrames();
  });

  it('with a mouse on a school opens it at once', () => {
    click(beside(map, PEMBROKE_HILL, 1, 1));
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    expect(pending).toEqual([]);
  });

  it('with a pen acts at once too', () => {
    click(beside(map, PEMBROKE_HILL, 1, 1), 1000, 'pen');
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('on a speck of dust opens its school as on a dot, and on several zooms in', () => {
    taps.stop();
    // The two about 10 px apart: a mouse reaches one, a finger both.
    map.zoom = 8;
    taps = attachSchoolTaps(map.map, {
      lit: () => null,
      dust: () => dust([PEMBROKE_HILL, BORDER_STAR]),
      onSchool: (school: SchoolHit) => actions.push(`open ${school.id}`),
      onZoom: () => actions.push('zoom'),
    });
    click(beside(map, BORDER_STAR, 0, 1));
    click(beside(map, PEMBROKE_HILL, 0, 2), 1000, 'touch');
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`open ${BORDER_STAR.id}`, 'zoom']);
  });

  it('on no school does nothing', () => {
    click(beside(map, PEMBROKE_HILL, 40, 0));
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(actions).toEqual([]);
  });

  it('twice with a mouse opens the school once, and its flight goes on: the map does not zoom', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    click(at);
    // The map's double click zoom is held off, so the second click leaves the flight be.
    expect(map.doubleClickZoom.isEnabled()).toBe(false);
    click(at, 150, 'mouse', 2);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    vi.advanceTimersByTime(DOUBLE_TAP_MS - 1);
    expect(map.doubleClickZoom.isEnabled()).toBe(false);
    vi.advanceTimersByTime(1);
    expect(map.doubleClickZoom.isEnabled()).toBe(true);
    // On no school, a double click is the map's: it zooms.
    const empty = beside(map, PEMBROKE_HILL, 60, 0);
    click(empty, 1000);
    click(empty, 150, 'mouse', 2);
    expect(map.doubleClickZoom.isEnabled()).toBe(true);
    // Long after, a click is a click again.
    click(at, 2000);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`, `open ${PEMBROKE_HILL.id}`]);
  });

  it('twice with a mouse keeps the first click’s flight: the second press takes no drag', () => {
    // MapLibre stops a flight at a press that starts a drag: the map's drag sits that press out.
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    const drags: boolean[] = [];
    map.on('mousedown', () => drags.push(map.dragPan.isEnabled()));
    click(at);
    click(at, 150, 'mouse', 2);
    expect(drags).toEqual([true, false]);
    vi.advanceTimersByTime(0);
    expect(map.dragPan.isEnabled()).toBe(true);
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    // A press on its own, long after, is the map's: a drag.
    click(beside(map, PEMBROKE_HILL, 60, 0), 2000);
    expect(drags).toEqual([true, false, true]);
    // A double click on no school acted on nothing: its second press drags as ever.
    click(beside(map, PEMBROKE_HILL, 60, 0), 150, 'mouse', 2);
    expect(drags).toEqual([true, false, true, true]);
  });

  it('after a press elsewhere stopped the flight a click set off, flies on, unless it moved the map', () => {
    const resumed: number[] = [];
    taps.stop();
    taps = attachSchoolTaps(map.map, {
      lit: () => null,
      onSchool: (school: SchoolHit) => actions.push(`open ${school.id}`),
      onZoom: (view) => actions.push(`zoom ${String(view.zoom)}`),
      onResume: () => resumed.push(now),
    });
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    const elsewhere = beside(map, PEMBROKE_HILL, 200, 80);
    click(at);
    map.moving = true;
    // A double click elsewhere as the flight sets off: its first press stops the flight
    // (MapLibre's drag), its click has it fly on; its second press takes no drag.
    const drags: boolean[] = [];
    map.on('mousedown', () => drags.push(map.dragPan.isEnabled()));
    click(elsewhere, 200);
    expect(resumed).toHaveLength(1);
    click(elsewhere, 100, 'mouse', 2);
    expect(drags).toEqual([true, false]);
    expect(resumed).toHaveLength(1);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    // A press that turns into a drag has no click: the map is the hand's.
    vi.advanceTimersByTime(0);
    click(at, 2000);
    map.fire('mousedown', {
      point: elsewhere,
      originalEvent: { timeStamp: now + 100, detail: 1, buttons: 1 },
    });
    expect(resumed).toHaveLength(1);
    // Past the hold, or with the map at rest, a click elsewhere is only a click.
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    click(elsewhere, 1000);
    map.moving = false;
    click(at, 1000);
    click(elsewhere, 100);
    expect(resumed).toHaveLength(1);
  });

  it('leaves the map’s double click zoom as it found it', () => {
    // Held off by the page itself: not given back by the taps.
    map.doubleClickZoom.disable();
    click(beside(map, PEMBROKE_HILL, 0, 0));
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(map.doubleClickZoom.isEnabled()).toBe(false);
    // Held off by the taps when they stop: given back.
    map.doubleClickZoom.enable();
    click(beside(map, PEMBROKE_HILL, 0, 0), 1000);
    taps.stop();
    expect(map.doubleClickZoom.isEnabled()).toBe(true);
  });

  it('with a finger shows the school picked at once, and opens it once no second tap follows', () => {
    click(beside(map, PEMBROKE_HILL, 10, 6), 1000, 'touch');
    expect(pending).toEqual([PEMBROKE_HILL.id]);
    vi.advanceTimersByTime(TAP_WAIT_MS - 1);
    expect(actions).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    // It stays picked: it is open.
    expect(pending).toEqual([PEMBROKE_HILL.id]);
  });

  it('reaches as far as its pointer does: a finger further than a mouse', () => {
    const off = beside(map, PEMBROKE_HILL, schoolDotRadius(map.zoom) + 10, 0);
    click(off, 1000, 'mouse');
    expect(actions).toEqual([]);
    click(off, 1000, 'touch');
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('reads a click with no pointer type by the last press on the map', () => {
    map.container.dispatchEvent(Object.assign(new Event('pointerdown'), { pointerType: 'touch' }));
    click(beside(map, PEMBROKE_HILL, schoolDotRadius(map.zoom) + 10, 0), 1000, '');
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('twice with a finger, a double tap, opens nothing and the school is no longer shown picked', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    click(at, 1000, 'touch');
    touchStart(at, 120);
    click(at, 60, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS * 2);
    expect(actions).toEqual([]);
    expect(pending).toEqual([PEMBROKE_HILL.id, null]);
  });

  it('with a finger at the map’s closest zoom opens at once: a double tap zooms no further', () => {
    map.zoom = 16;
    click(beside(map, PEMBROKE_HILL, 0, 0), 1000, 'touch');
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    expect(pending).toEqual([]);
  });

  it('whose second tap comes after the school opened keeps the pick’s flight: the map does not zoom', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    click(at, 1000, 'touch');
    expect(map.doubleClickZoom.isEnabled()).toBe(true);
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    expect(map.doubleClickZoom.isEnabled()).toBe(false);
    touchStart(at, TAP_WAIT_MS + 50);
    click(at, 60, 'touch');
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(map.doubleClickZoom.isEnabled()).toBe(true);
  });

  it('on several schools zooms in toward them, and opens none', () => {
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }, eastOf(map, '290000000001', 16)];
    const between = beside(map, PEMBROKE_HILL, 8, 0);
    click(between);
    expect(actions).toEqual([`zoom ${String(map.zoom + DRILL_STEP)}`]);
    // A finger's waits for a second tap first, and shows no school picked.
    actions = [];
    click(between, 1000, 'touch');
    expect(pending).toEqual([]);
    expect(actions).toEqual([]);
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`zoom ${String(map.zoom + DRILL_STEP)}`]);
  });

  it('with a finger is let go when the map is moved by hand, pressed again, or turned by a wheel', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    for (const type of ['movestart', 'mousedown', 'wheel', 'touchstart']) {
      pending = [];
      click(at, 1000, 'touch');
      const originalEvent = { timeStamp: now + 100, touches: [{}] };
      map.fire(type, { point: { x: 700, y: 50 }, originalEvent });
      vi.advanceTimersByTime(DOUBLE_TAP_MS);
      expect(actions, type).toEqual([]);
      expect(pending, type).toEqual([PEMBROKE_HILL.id, null]);
    }
    // The map's own moves (a flight) leave it be.
    click(at, 1000, 'touch');
    map.fire('movestart', {});
    vi.advanceTimersByTime(TAP_WAIT_MS);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('heard after a press that came after it opens nothing: a busy page’s late click', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    // A double tap whose first click comes after the second touch.
    touchStart(at, 150);
    now -= 100;
    click(at, 0, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(actions).toEqual([]);
  });

  it('while two fingers are on the map opens nothing', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    touchStart(at, 100, 2);
    click(at, 50, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(actions).toEqual([]);
    map.fire('touchend', { originalEvent: { touches: [] } });
    click(at, 1000, 'touch');
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('heard before the taps were attached is taken as one', () => {
    const at = beside(map, PEMBROKE_HILL, 0, 0);
    now += 1000;
    taps.click({
      point: at,
      originalEvent: { timeStamp: now, detail: 1, pointerType: 'mouse' },
    } as unknown as Parameters<SchoolTaps['click']>[0]);
    expect(actions).toEqual([`open ${PEMBROKE_HILL.id}`]);
  });

  it('acts on nothing once the taps are stopped, and a school shown picked is let go', () => {
    click(beside(map, PEMBROKE_HILL, 0, 0), 1000, 'touch');
    taps.stop();
    vi.advanceTimersByTime(DOUBLE_TAP_MS);
    expect(actions).toEqual([]);
    expect(pending).toEqual([PEMBROKE_HILL.id, null]);
    click(beside(map, PEMBROKE_HILL, 0, 0));
    expect(actions).toEqual([]);
  });
});

describe('a press on the map', () => {
  let map: FakeMap;
  let spots: LitSpots | null;
  let pressed: string[];
  let taps: SchoolTaps;
  const press = (point: { x: number; y: number }, pointerType = 'mouse') => {
    map.fire('mousedown', { point, originalEvent: { timeStamp: 0, detail: 1, pointerType } });
  };
  const touch = (point: { x: number; y: number }, fingers = 1) => {
    const touches = Array.from({ length: fingers }, () => ({}));
    map.fire('touchstart', { point, originalEvent: { timeStamp: 0, touches } });
  };

  beforeEach(() => {
    fakeFrames();
    // The national view: no dots drawn, a lit school's light alone.
    map = new FakeMap();
    map.zoom = 4;
    map.layers = new Set();
    spots = lit([BORDER_STAR]);
    pressed = [];
    taps = attachSchoolTaps(map.map, {
      lit: () => spots,
      onSchool: () => undefined,
      onZoom: () => undefined,
      onPress: (school) => pressed.push(school.id),
    });
  });

  afterEach(() => {
    taps.stop();
    realFrames();
  });

  it('where a tap opens a school, by its light alone, says so before any click', () => {
    press(beside(map, BORDER_STAR, 0, 4));
    expect(pressed).toEqual([BORDER_STAR.id]);
    // As far as its pointer reaches: a finger further than a mouse.
    const off = beside(map, BORDER_STAR, 0, litRadius(map.zoom) + HIT_RADIUS.mouse + 4);
    press(off);
    expect(pressed).toHaveLength(1);
    touch(off);
    expect(pressed).toEqual([BORDER_STAR.id, BORDER_STAR.id]);
    // A school's dot, drawn up close, as well.
    map.zoom = 14;
    map.layers = new Set([BASEMAP_IDS.schoolDots]);
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    press(beside(map, PEMBROKE_HILL, 1, 1));
    expect(pressed).toEqual([BORDER_STAR.id, BORDER_STAR.id, PEMBROKE_HILL.id]);
  });

  it('where a tap opens none, as on nothing, on several, or under two fingers, says nothing', () => {
    press(beside(map, BORDER_STAR, 0, 40));
    touch(beside(map, BORDER_STAR, 0, 0), 2);
    spots = lit([PEMBROKE_HILL, BORDER_STAR]);
    press(beside(map, BORDER_STAR, 0, 3));
    spots = null;
    press(beside(map, BORDER_STAR, 0, 0));
    expect(pressed).toEqual([]);
  });
});

describe('the cursor', () => {
  let map: FakeMap;
  let looks: number;
  let spots: LitSpots | null;
  let taps: SchoolTaps;
  const move = (point: { x: number; y: number }, buttons = 0) => {
    map.fire('mousemove', { point, originalEvent: { buttons } });
  };
  const pointer = (): boolean => map.container.classList.contains(POINTER_CLASS);

  beforeEach(() => {
    fakeFrames();
    map = new FakeMap();
    map.drawn = [{ ...PEMBROKE_HILL, name: 'Pembroke Hill' }];
    looks = 0;
    spots = null;
    taps = attachSchoolTaps(map.map, {
      lit: () => {
        looks += 1;
        return spots;
      },
      onSchool: () => undefined,
      onZoom: () => undefined,
    });
  });

  afterEach(() => {
    taps.stop();
    realFrames();
  });

  it('is a pointer over a school and the map’s own elsewhere, looked for once a frame', () => {
    for (let dx = 20; dx >= 0; dx -= 2) move(beside(map, PEMBROKE_HILL, dx, 0));
    expect(pointer()).toBe(false);
    nextFrame();
    expect(looks).toBe(1);
    expect(pointer()).toBe(true);
    move(beside(map, PEMBROKE_HILL, 30, 0));
    nextFrame();
    expect(pointer()).toBe(false);
    // Dragging, it is the map's; off the map, it is gone.
    move(beside(map, PEMBROKE_HILL, 0, 0));
    nextFrame();
    expect(pointer()).toBe(true);
    move(beside(map, PEMBROKE_HILL, 0, 0), 1);
    expect(pointer()).toBe(false);
    move(beside(map, PEMBROKE_HILL, 0, 0));
    nextFrame();
    map.fire('mouseout', {});
    expect(pointer()).toBe(false);
    move(beside(map, PEMBROKE_HILL, 0, 0));
    nextFrame();
    taps.stop();
    expect(pointer()).toBe(false);
  });

  it('turns to a pointer when the glow lights a school under a still mouse', () => {
    map.drawn = [];
    move(beside(map, BORDER_STAR, 1, 0));
    nextFrame();
    expect(pointer()).toBe(false);
    // The map draws frames with nothing new: nothing is looked for again.
    const before = looks;
    map.fire('render', {});
    nextFrame();
    expect(pointer()).toBe(false);
    // The glow lights Border Star, and draws it.
    spots = lit([BORDER_STAR]);
    map.fire('render', {});
    nextFrame();
    expect(pointer()).toBe(true);
    expect(looks).toBeGreaterThan(before);
  });
});

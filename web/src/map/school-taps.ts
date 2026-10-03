/**
 * A school opens from the map itself: a click or a tap on its mark opens it
 * as a pick of it in search would (app/boot.ts hands it to the page, which
 * takes the pick's own path).
 *
 * A school's marks are what the map shows of it, while it shows them: its dot
 * and its name, each once it is drawn at the map's zoom (basemap/schools.ts
 * says from which zoom, and how big), and the glow's light of a school lit
 * today, at every zoom, found from the glow's own data (glow-mount.ts). A mark
 * is in reach of the pointer within a hit radius of its edge: HIT_RADIUS.mouse
 * for a mouse or a pen, HIT_RADIUS.touch for a finger, as the pointer that
 * pressed says. A name is in reach only under the pointer.
 *
 * A tap opens a school only where it means one: the one mark under the
 * pointer, or else the one mark in reach. Where it could mean several (a
 * metro's lights at the national view, a cluster of dots), it opens none: the
 * map zooms in toward them instead, into the part of the map in view, clear
 * of the panel or the sheet shown over it, if any (app/frame.ts mapInView),
 * as far as keeps them all in it, to DRILL_ZOOM at most and by DRILL_STEP
 * levels at least, so tap by tap it comes down to one school under the
 * finger. Schools no zoom tells apart (one campus, one place) open the
 * nearest.
 *
 * Only a click acts: MapLibre fires none for a drag or a pinch. A press
 * where a tap would open a school, its light included, says so at once
 * (onPress), so what its streets need can come before the click. A mouse's
 * or a pen's click acts at once. MapLibre stops a flight at any gesture it
 * takes, a press to drag the map as much as a double click's zoom. So for
 * DOUBLE_TAP_MS after a tap acts, the map's double click zoom is held off
 * and the second press of a double click takes no drag, and a press that
 * stops the flight without moving the map (a click elsewhere) has it go on
 * where it was going (onResume): the map arrives. A finger's tap waits
 * TAP_WAIT_MS for a second tap, as a double tap zooms the map instead, while
 * the school it would open shows as picked and its panel starts to load
 * (onPending); at the map's closest zoom, where a double tap zooms no
 * further, it acts at once. A press, a hand moving the map or a wheel in that
 * time lets the tap go, as events' own times tell, so a busy page that hears
 * a tap's click after the next touch acts on nothing either. A click heard
 * before this code was in comes as the map shows it now (kept-clicks.ts).
 *
 * With a mouse, the cursor is a pointer over a mark a click would act on,
 * looked for once an animation frame at most while the mouse moves, and
 * again when the map comes to rest or the glow lights other schools under a
 * still mouse. A click on no school does nothing: a panel open stays open.
 */
import type { Map as MapLibreMap, MapMouseEvent, MapTouchEvent, PointLike } from 'maplibre-gl';

import { SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import type { LitSchools } from '../data/closings';
import { displayName } from '../text/names';
import { stateOfId } from '../text/school-names';
import type { SchoolId } from '../types/generated';
// From the modules that draw the marks, loaded before this one (their own chunks, not copies).
import { schoolDotOpacity, schoolDotRadius, schoolNameOpacity } from './basemap';
import type { MapView } from './basemap';
import { BASEMAP_IDS, SCHOOL_LIT_STATE } from './basemap/ids';
import { litRadius } from './glow-mount';
import type { HeardClick } from './kept-clicks';
import {
  latFromMercatorY,
  lngFromMercatorX,
  mercatorXFromLng,
  mercatorYFromLat,
} from './glow/mercator';

/** How far from a mark's edge the pointer may be and still reach it, in CSS pixels. */
export const HIT_RADIUS = Object.freeze({ mouse: 6, touch: 16 });

/** How long a finger's tap waits for a second tap before it acts, in milliseconds. */
export const TAP_WAIT_MS = 250;

/**
 * A click this soon after the one before it, and this near it, is the second
 * of a double click or a double tap: MapLibre's own limits for a double tap
 * (its tap_recognizer.ts), in milliseconds and CSS pixels.
 */
export const DOUBLE_TAP_MS = 500;
export const DOUBLE_TAP_PX = 30;

/** A mark takes clicks from this opacity: half drawn, fading in. */
export const SHOWN_OPACITY = 0.5;

/**
 * A tap that could mean several schools zooms in toward them: to this zoom at
 * most, where a metro's schools stand apart, and by this many levels at least.
 */
export const DRILL_ZOOM = 11;
export const DRILL_STEP = 2;
/** Room kept between the schools it zooms toward and the edge of where it puts them, in CSS pixels. */
export const DRILL_MARGIN = 48;
/** Schools this close at the map's closest zoom, in CSS pixels, are at one place. */
const ONE_PLACE_PX = 2;
/** A zoom in by less than this many levels tells nothing apart. */
const LEAST_DRILL = 0.5;

/** MapLibre's own class for a pointer over the map, which index.html styles as a pointer. */
export const POINTER_CLASS = 'maplibregl-track-pointer';

/** MapLibre's world size at zoom 0, in CSS pixels. */
const TILE = 512;

/** A school a tap opens. */
export interface SchoolHit {
  readonly id: SchoolId;
  /** Its name as the map shows it. */
  readonly name: string;
  readonly lon: number;
  readonly lat: number;
}

/** A school's mark in reach of the pointer. */
export interface MarkHit {
  readonly id: SchoolId;
  readonly lon: number;
  readonly lat: number;
  /** Where its center is from the pointer, in CSS pixels. */
  readonly dx: number;
  readonly dy: number;
  /** How far the pointer is from the mark's edge, in CSS pixels: 0 with the mark under it. */
  readonly distance: number;
  /** Its name as the map shows it, worked out for the school a tap opens. */
  name(): string;
}

/** A part of the map, in CSS pixels from its top left corner (app/frame.ts Area). */
export interface MapArea {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
}

/** What a tap does: open a school, or zoom in toward several. */
export type TapAction =
  | { readonly kind: 'open'; readonly school: SchoolHit }
  | { readonly kind: 'zoom'; readonly view: MapView };

/** The glow's lit schools, as far as finding them goes. */
export type LitSpots = Pick<LitSchools, 'lngLat' | 'ids' | 'names'>;

/** The hit radius for a pointer of this type (PointerEvent.pointerType): a finger's, or a mouse's. */
export function hitRadius(pointerType: string): number {
  return pointerType === 'touch' ? HIT_RADIUS.touch : HIT_RADIUS.mouse;
}

/** A lit school's name as the map shows it (school-tiles.ts shows the tiles' the same way). */
function shownName(id: SchoolId, written: string): string {
  return displayName(written, { state: stateOfId(id) }, SCHOOL_NAME_FIXES[id] ?? {});
}

/** Each lit set's places in Web Mercator, worked out once for the set. */
const mercatorOf = new WeakMap<LitSpots, Float64Array>();

function mercator(lit: LitSpots): Float64Array {
  let points = mercatorOf.get(lit);
  if (points === undefined) {
    const count = lit.lngLat.length / 2;
    points = new Float64Array(count * 2);
    for (let i = 0; i < count; i++) {
      points[i * 2] = mercatorXFromLng(lit.lngLat[i * 2] ?? 0);
      points[i * 2 + 1] = mercatorYFromLat(lit.lngLat[i * 2 + 1] ?? 0);
    }
    mercatorOf.set(lit, points);
  }
  return points;
}

/**
 * The lit schools whose light is within `radius` CSS pixels of the pointer,
 * from the glow's data: `at` is the pointer in Web Mercator units, `scale`
 * the CSS pixels to one unit (the world's size at the map's zoom) and `mark`
 * the light's own radius. The map is never tilted or turned, so a distance in
 * Mercator is one on the screen.
 */
export function litInReach(
  lit: LitSpots,
  at: { readonly x: number; readonly y: number },
  scale: number,
  radius: number,
  mark: number,
): MarkHit[] {
  const points = mercator(lit);
  const reach = (radius + mark) / scale;
  const hits: MarkHit[] = [];
  for (let i = 0; i < lit.ids.length; i++) {
    const x = points[i * 2] ?? Number.NaN;
    const y = points[i * 2 + 1] ?? Number.NaN;
    if (!(Math.abs(x - at.x) <= reach && Math.abs(y - at.y) <= reach)) continue;
    const dx = (x - at.x) * scale;
    const dy = (y - at.y) * scale;
    const distance = Math.max(0, Math.hypot(dx, dy) - mark);
    const id = lit.ids[i];
    if (id === undefined || !(distance <= radius)) continue;
    const written = lit.names[i] ?? '';
    hits.push({
      id,
      lon: lit.lngLat[i * 2] ?? 0,
      lat: lit.lngLat[i * 2 + 1] ?? 0,
      dx,
      dy,
      distance,
      name: () => shownName(id, written),
    });
  }
  return hits;
}

/** A feature of the school layers as a school (schools.ts reads the same properties), or null. */
function featureSchool(feature: {
  readonly properties: Record<string, unknown>;
  readonly geometry: unknown;
}): { id: SchoolId; name: string; lon: number; lat: number } | null {
  const { id, name } = feature.properties;
  const geometry = feature.geometry as { type?: unknown; coordinates?: unknown };
  if (typeof id !== 'string' || geometry.type !== 'Point') return null;
  const [lon, lat] = Array.isArray(geometry.coordinates) ? (geometry.coordinates as unknown[]) : [];
  if (typeof lon !== 'number' || typeof lat !== 'number') return null;
  return { id, name: typeof name === 'string' ? name : '', lon, lat };
}

/**
 * Every school with a mark in reach of the pointer at `point` (CSS pixels on
 * the map), each once, by its nearest mark: its dot and its name as the map
 * draws them now, and its light when the glow lights it.
 */
export function schoolsInReach(
  map: MapLibreMap,
  point: { readonly x: number; readonly y: number },
  radius: number,
  lit: LitSpots | null,
): MarkHit[] {
  const zoom = map.getZoom();
  const found = new Map<SchoolId, MarkHit>();
  const add = (hit: MarkHit): void => {
    const known = found.get(hit.id);
    if (known === undefined || hit.distance < known.distance) found.set(hit.id, hit);
  };
  const { schoolDots, schoolNames } = BASEMAP_IDS;
  const drawn = (id: string, opacity: number): boolean =>
    opacity >= SHOWN_OPACITY && map.getLayer(id) !== undefined;
  if (drawn(schoolDots, schoolDotOpacity(zoom))) {
    const mark = schoolDotRadius(zoom);
    const box: [PointLike, PointLike] = [
      [point.x - radius - mark, point.y - radius - mark],
      [point.x + radius + mark, point.y + radius + mark],
    ];
    for (const feature of map.queryRenderedFeatures(box, { layers: [schoolDots] })) {
      // A school the glow lights shows its light, not its dot.
      if (feature.state[SCHOOL_LIT_STATE] === true) continue;
      const school = featureSchool(feature);
      if (school === null) continue;
      const at = map.project([school.lon, school.lat]);
      const dx = at.x - point.x;
      const dy = at.y - point.y;
      const distance = Math.max(0, Math.hypot(dx, dy) - mark);
      if (distance <= radius) add({ ...school, dx, dy, distance, name: () => school.name });
    }
  }
  if (drawn(schoolNames, schoolNameOpacity(zoom))) {
    for (const feature of map.queryRenderedFeatures([point.x, point.y], {
      layers: [schoolNames],
    })) {
      const school = featureSchool(feature);
      if (school === null) continue;
      const at = map.project([school.lon, school.lat]);
      add({
        ...school,
        dx: at.x - point.x,
        dy: at.y - point.y,
        distance: 0,
        name: () => school.name,
      });
    }
  }
  if (lit !== null && lit.ids.length > 0) {
    const { lng, lat } = map.unproject([point.x, point.y]);
    const at = { x: mercatorXFromLng(lng), y: mercatorYFromLat(lat) };
    for (const hit of litInReach(lit, at, TILE * 2 ** zoom, radius, litRadius(zoom))) add(hit);
  }
  return [...found.values()];
}

/** The marks a tap could mean: those under the pointer, or else all in reach. */
function candidates(marks: readonly MarkHit[]): readonly MarkHit[] {
  const under = marks.filter((mark) => mark.distance <= 0);
  return under.length > 0 ? under : marks;
}

/** The one school a tap on these marks means, or null: none in reach, or several. */
export function meantSchool(marks: readonly MarkHit[]): MarkHit | null {
  const pool = candidates(marks);
  return pool.length === 1 ? (pool[0] ?? null) : null;
}

/**
 * Where a tap at `point` on several schools zooms to: the middle of them in
 * the middle of `area` (the part of the map in view, clear of any panel),
 * as far in as keeps them all DRILL_MARGIN inside it, to DRILL_ZOOM at most
 * and by DRILL_STEP levels at least, no closer than the map goes. Null where
 * no zoom tells them apart: they are at one place, or the map is as close as
 * it goes.
 */
export function drillView(
  map: MapLibreMap,
  point: { readonly x: number; readonly y: number },
  pool: readonly MarkHit[],
  area: MapArea,
): MapView | null {
  const zoom = map.getZoom();
  const closest = map.getMaxZoom();
  const xs = pool.map((mark) => mark.dx);
  const ys = pool.map((mark) => mark.dy);
  const [left, right, top, bottom] = [
    Math.min(...xs),
    Math.max(...xs),
    Math.min(...ys),
    Math.max(...ys),
  ];
  if (!(Math.hypot(right - left, bottom - top) * 2 ** (closest - zoom) >= ONE_PLACE_PX)) {
    return null;
  }
  // The middle of them, on the screen now, and where it goes: the middle of the area.
  const middle = { x: point.x + (left + right) / 2, y: point.y + (top + bottom) / 2 };
  const to = { x: (area.left + area.right) / 2, y: (area.top + area.bottom) / 2 };
  // How many times further apart they can be and all stay in the area, around its middle.
  const half = { x: (right - left) / 2, y: (bottom - top) / 2 };
  const room = Math.min(
    half.x > 0 ? ((area.right - area.left) / 2 - DRILL_MARGIN) / half.x : Infinity,
    half.y > 0 ? ((area.bottom - area.top) / 2 - DRILL_MARGIN) / half.y : Infinity,
  );
  const fit = zoom + Math.log2(Math.max(room, 0));
  const target = Math.min(closest, Math.max(Math.min(fit, DRILL_ZOOM), zoom + DRILL_STEP));
  if (target - zoom < LEAST_DRILL) return null;
  const { lng, lat } = map.unproject([middle.x, middle.y]);
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  const scale = TILE * 2 ** target;
  const x = mercatorXFromLng(lng) - (to.x - width / 2) / scale;
  const y = mercatorYFromLat(lat) - (to.y - height / 2) / scale;
  return { lat: latFromMercatorY(y), lon: lngFromMercatorX(x), zoom: target };
}

function opens(mark: MarkHit): TapAction {
  return {
    kind: 'open',
    school: { id: mark.id, name: mark.name(), lon: mark.lon, lat: mark.lat },
  };
}

/** The whole map, as an area. */
function wholeMap(map: MapLibreMap): MapArea {
  const { clientWidth, clientHeight } = map.getContainer();
  return { left: 0, top: 0, right: clientWidth, bottom: clientHeight };
}

/**
 * What a tap at `point` does with this hit radius, or null for nothing: no
 * school in reach. A zoom toward several fits them into `area`.
 */
export function tapAction(
  map: MapLibreMap,
  point: { readonly x: number; readonly y: number },
  radius: number,
  lit: LitSpots | null,
  area: MapArea = wholeMap(map),
): TapAction | null {
  const marks = schoolsInReach(map, point, radius, lit);
  if (marks.length === 0) return null;
  const pool = candidates(marks);
  const one = meantSchool(marks);
  if (one !== null) return opens(one);
  const view = drillView(map, point, pool, area);
  if (view !== null) return { kind: 'zoom', view };
  // Nothing tells them apart: the nearest, the nearest center among marks under the pointer.
  const nearest = pool.reduce((best, mark) =>
    mark.distance < best.distance ||
    (mark.distance === best.distance && Math.hypot(mark.dx, mark.dy) < Math.hypot(best.dx, best.dy))
      ? mark
      : best,
  );
  return opens(nearest);
}

export interface SchoolTapOptions {
  /** The schools the glow lights now, or null for none. */
  readonly lit: () => LitSpots | null;
  /** A school was clicked or tapped: open it. */
  readonly onSchool: (school: SchoolHit) => void;
  /** A tap could mean several schools: zoom in toward them. */
  readonly onZoom: (view: MapView) => void;
  /**
   * A finger's tap on a school, waiting to be sure it is no double tap: show
   * it picked, and start loading its panel. Null once it turns out to be one.
   */
  readonly onPending?: (school: SchoolHit | null) => void;
  /**
   * A press stopped the flight a tap set off, without moving the map: fly on
   * to where it was going.
   */
  readonly onResume?: () => void;
  /**
   * A press where a tap would open a school, before any click: what its
   * streets need can start coming.
   */
  readonly onPress?: (school: SchoolHit) => void;
  /** The part of the map in view as a tap comes, clear of any panel; the whole map by default. */
  readonly area?: () => MapArea;
}

/** The taps on the map: stopped when the page goes. */
export interface SchoolTaps {
  /** Takes a click heard before the taps were attached, as the map shows it now (kept-clicks.ts). */
  click(event: HeardClick): void;
  stop(): void;
}

/** A click, as the next one is measured against. */
interface Click {
  readonly time: number;
  readonly x: number;
  readonly y: number;
  /** Whether it opened a school or zoomed the map. */
  acted: boolean;
}

/** Opens the school a click or a tap on the map means, and shows a pointer over one with a mouse. */
export function attachSchoolTaps(map: MapLibreMap, options: SchoolTapOptions): SchoolTaps {
  const container = map.getCanvasContainer();
  /** The type of the pointer that last pressed on the map. */
  let pointerType = 'mouse';
  let last: Click | null = null;
  let pending: ReturnType<typeof setTimeout> | undefined;
  /** The school a waiting tap shows as picked, if any. */
  let shown: SchoolHit | null = null;
  /** True while two fingers or more are on the map. */
  let pinching = false;
  /** When the map was last pressed, moved by hand or turned by a wheel, as an event's timeStamp. */
  let touched = -Infinity;
  /** While the map's double click zoom is held off after a tap acted: when it comes back. */
  let zoomBack: ReturnType<typeof setTimeout> | undefined;
  /** While a press takes no drag: when the map's drag comes back. */
  let dragBack: ReturnType<typeof setTimeout> | undefined;
  /** Whether the last press stopped a tap's flight, and its click, if it moved nothing, resumes it. */
  let stopped = false;

  /** A waiting tap acts on nothing; the school it showed as picked is shown so no longer. */
  const cancel = (): void => {
    clearTimeout(pending);
    pending = undefined;
    if (shown === null) return;
    shown = null;
    options.onPending?.(null);
  };
  /** A press, a hand moving the map or a wheel: a tap waiting to act acts on nothing. */
  const interrupt = (event: { readonly originalEvent?: Event | undefined }): void => {
    // A move without an event is the map's own (a flight).
    const time = event.originalEvent?.timeStamp;
    if (time === undefined) return;
    touched = Math.max(touched, time);
    cancel();
  };
  /** The type of the pointer behind an event: its own, else the last to press on the map. */
  const typeOf = (event: Event): string =>
    ('pointerType' in event && typeof event.pointerType === 'string' ? event.pointerType : '') ||
    pointerType;
  /** A press where a tap would open a school: onPress hears of it. */
  const pressed = (point: { readonly x: number; readonly y: number }, type: string): void => {
    if (options.onPress === undefined) return;
    const action = tapAction(map, point, hitRadius(type), options.lit());
    if (action?.kind === 'open') options.onPress(action.school);
  };
  /** Whether a press or a click at this time and place is the second of a double click on `click`. */
  const secondOf = (click: Click | null, time: number, x: number, y: number): boolean =>
    click !== null &&
    time - click.time >= 0 &&
    time - click.time < DOUBLE_TAP_MS &&
    Math.hypot(x - click.x, y - click.y) < DOUBLE_TAP_PX;

  /** The map's double click zoom back, if it is held off. */
  const giveZoomBack = (): void => {
    if (zoomBack === undefined) return;
    clearTimeout(zoomBack);
    zoomBack = undefined;
    map.doubleClickZoom.enable();
  };
  /** The map's drag back, if a press took none. */
  const giveDragBack = (): void => {
    if (dragBack === undefined) return;
    clearTimeout(dragBack);
    dragBack = undefined;
    map.dragPan.enable();
  };
  /**
   * A press on the map: a tap waiting to act lets go. For DOUBLE_TAP_MS
   * after a tap acted, the second press of a double click takes no drag,
   * which would stop the flight the tap set off (the map's drag is back once
   * MapLibre has had the press); any other press on the flying map stops it,
   * and if that press moves nothing, its click has the flight go on.
   */
  const onMouseDown = (event: MapMouseEvent): void => {
    const { originalEvent, point } = event;
    const holding = zoomBack !== undefined;
    const second =
      originalEvent.detail > 1 || secondOf(last, originalEvent.timeStamp, point.x, point.y);
    if (holding && second && map.dragPan.isEnabled()) {
      map.dragPan.disable();
      dragBack = setTimeout(giveDragBack, 0);
    } else {
      stopped = holding && map.isMoving();
    }
    interrupt(event);
    pressed(point, typeOf(originalEvent));
  };
  const act = (action: TapAction): void => {
    // A second click or tap coming now is the second of a double: it leaves the flight be.
    if (zoomBack !== undefined || map.doubleClickZoom.isEnabled()) {
      clearTimeout(zoomBack);
      map.doubleClickZoom.disable();
      zoomBack = setTimeout(giveZoomBack, DOUBLE_TAP_MS);
    }
    if (last !== null) last.acted = true;
    if (action.kind === 'open') options.onSchool(action.school);
    else options.onZoom(action.view);
  };
  const onPointerDown = (event: PointerEvent): void => {
    pointerType = event.pointerType;
  };
  /** Reads a click: true where it acts, now or once no second tap follows. */
  const read = (event: HeardClick): boolean => {
    const { originalEvent, point } = event;
    const time = originalEvent.timeStamp;
    // The second click of a double click, or a third: the first has acted, or the map zooms.
    if (originalEvent.detail > 1 || secondOf(last, time, point.x, point.y)) return false;
    // Nor while fingers pinch, or for a click older than a press after it (a busy page's).
    if (pinching || touched > time) return false;
    last = { time, x: point.x, y: point.y, acted: false };
    cancel();
    const type = typeOf(originalEvent);
    const action = tapAction(map, point, hitRadius(type), options.lit(), options.area?.());
    if (action === null) return false;
    // A mouse or a pen acts at once, and so does a finger where a double tap zooms no further.
    if (type !== 'touch' || map.getZoom() >= map.getMaxZoom()) {
      act(action);
      return true;
    }
    if (action.kind === 'open') {
      shown = action.school;
      options.onPending?.(shown);
    }
    pending = setTimeout(() => {
      pending = undefined;
      shown = null;
      act(action);
    }, TAP_WAIT_MS);
    return true;
  };
  const onClick = (event: HeardClick): void => {
    // After a press that stopped a tap's flight and moved nothing: unless this click acts, the
    // flight goes on.
    const resume = stopped;
    stopped = false;
    if (!read(event) && resume) options.onResume?.();
  };
  const onTouchStart = (event: MapTouchEvent): void => {
    interrupt(event);
    if (event.originalEvent.touches.length > 1) pinching = true;
    else pressed(event.point, 'touch');
  };
  const onTouchEnd = (event: MapTouchEvent): void => {
    if (event.originalEvent.touches.length === 0) pinching = false;
  };

  /** Where the mouse is over the map, or null when it is not. */
  let hover: { x: number; y: number } | null = null;
  let frame: number | undefined;
  let pointing = false;
  /** The lit schools the cursor was last looked for among. */
  let seen: LitSpots | null = null;
  const point = (on: boolean): void => {
    if (on === pointing) return;
    pointing = on;
    container.classList.toggle(POINTER_CLASS, on);
  };
  const lookUnderMouse = (): void => {
    frame = undefined;
    seen = options.lit();
    point(hover !== null && schoolsInReach(map, hover, HIT_RADIUS.mouse, seen).length > 0);
  };
  const lookSoon = (): void => {
    frame ??= requestAnimationFrame(lookUnderMouse);
  };
  const onMouseMove = (event: MapMouseEvent): void => {
    // A button held down is a drag: the map's own cursor shows.
    if (event.originalEvent.buttons !== 0) {
      hover = null;
      point(false);
      return;
    }
    hover = { x: event.point.x, y: event.point.y };
    lookSoon();
  };
  const onMouseOut = (): void => {
    hover = null;
    point(false);
  };
  // The map moved under a still mouse: another school may be under it now.
  const onMoveEnd = (): void => {
    if (hover !== null) lookSoon();
  };
  // The glow lit other schools under a still mouse, and drew them.
  const onRender = (): void => {
    if (hover !== null && options.lit() !== seen) lookSoon();
  };

  container.addEventListener('pointerdown', onPointerDown, { passive: true });
  map.on('click', onClick);
  map.on('mousedown', onMouseDown);
  map.on('touchstart', onTouchStart);
  map.on('touchend', onTouchEnd);
  map.on('touchcancel', onTouchEnd);
  map.on('movestart', interrupt);
  map.on('wheel', interrupt);
  map.on('mousemove', onMouseMove);
  map.on('mouseout', onMouseOut);
  map.on('moveend', onMoveEnd);
  map.on('render', onRender);
  return {
    click: onClick,
    stop() {
      cancel();
      giveZoomBack();
      giveDragBack();
      if (frame !== undefined) cancelAnimationFrame(frame);
      point(false);
      container.removeEventListener('pointerdown', onPointerDown);
      map.off('click', onClick);
      map.off('mousedown', onMouseDown);
      map.off('touchstart', onTouchStart);
      map.off('touchend', onTouchEnd);
      map.off('touchcancel', onTouchEnd);
      map.off('movestart', interrupt);
      map.off('wheel', interrupt);
      map.off('mousemove', onMouseMove);
      map.off('mouseout', onMouseOut);
      map.off('moveend', onMoveEnd);
      map.off('render', onRender);
    },
  };
}

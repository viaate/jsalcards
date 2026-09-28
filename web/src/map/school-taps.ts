/**
 * A school opens from the map itself: a click or a tap on its dot, its name,
 * or its light opens it as a pick of it in search would (app/boot.ts hands it
 * to the page, which takes the pick's own path).
 *
 * The pointer means the school nearest it among those within a hit radius of
 * it: HIT_RADIUS.mouse for a mouse or a pen, HIT_RADIUS.touch for a finger,
 * as the pointer that pressed says. Where a name is under the pointer, that
 * school is meant; a name only beside it counts as the edge of the radius.
 * Dots and names are what MapLibre drew (the school layers, basemap/ids.ts),
 * from zoom 11. A school lit today is found from the glow's own data, where it
 * is and which school it is (glow-mount.ts), so its light takes a tap at every
 * zoom, the national view's small lights too.
 *
 * Only a click opens a school: MapLibre fires none for a drag or a pinch. A
 * click waits OPEN_AFTER_MS for a second one, and the two of a double click
 * or a double tap open nothing, so the map zooms in and nothing fights it; a
 * press, a hand moving the map or a wheel in that time also cancels it, as
 * events' own times tell, so a busy page that hears a tap's click after the
 * next touch opens nothing either. Where the second click of a slow double
 * click comes after the school has opened, the map's zoom gives way to the
 * pick's flight.
 *
 * With a mouse, the cursor is a pointer over a school that would open, looked
 * for once an animation frame at most while the mouse moves. A click on no
 * school does nothing: a panel open stays open.
 */
import type { Map as MapLibreMap, MapMouseEvent, MapTouchEvent, PointLike } from 'maplibre-gl';

import { SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import type { LitSchools } from '../data/closings';
import { displayName } from '../text/names';
import { stateOfId } from '../text/school-names';
import type { SchoolId } from '../types/generated';
import { BASEMAP_IDS } from './basemap/ids';
import { mercatorXFromLng, mercatorYFromLat } from './glow/mercator';

/** How far from a school the pointer may be and still mean it, in CSS pixels. */
export const HIT_RADIUS = Object.freeze({ mouse: 6, touch: 16 });

/** How long a click on a school waits for a second click before the school opens, in milliseconds. */
export const OPEN_AFTER_MS = 300;

/**
 * A click this soon after the one before it, and this near it, is the second
 * of a double click or a double tap: MapLibre's own limits for a double tap
 * (its tap_recognizer.ts), in milliseconds and CSS pixels.
 */
export const DOUBLE_TAP_MS = 500;
export const DOUBLE_TAP_PX = 30;

/** MapLibre's own class for a pointer over the map, which index.html styles as a pointer. */
export const POINTER_CLASS = 'maplibregl-track-pointer';

/** MapLibre's world size at zoom 0, in CSS pixels. */
const TILE = 512;

/** A school the pointer may mean. */
export interface SchoolHit {
  readonly id: SchoolId;
  /** Its name as the map shows it. */
  readonly name: string;
  readonly lon: number;
  readonly lat: number;
  /** How far it is from the pointer, in CSS pixels. */
  readonly distance: number;
}

/** The glow's lit schools, as far as finding them goes. */
export type LitSpots = Pick<LitSchools, 'lngLat' | 'ids' | 'names'>;

/** The hit radius for a pointer of this type (PointerEvent.pointerType): a finger's, or a mouse's. */
export function hitRadius(pointerType: string): number {
  return pointerType === 'touch' ? HIT_RADIUS.touch : HIT_RADIUS.mouse;
}

/** The school nearest the pointer among those within `radius` of it, or null for none. */
export function nearestSchool(hits: Iterable<SchoolHit>, radius: number): SchoolHit | null {
  let best: SchoolHit | null = null;
  for (const hit of hits) {
    if (!(hit.distance <= radius)) continue;
    if (best === null || hit.distance < best.distance) best = hit;
  }
  return best;
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
 * The lit school nearest the pointer within `radius` CSS pixels of it, from
 * the glow's data, or null: `at` is the pointer in Web Mercator units, and
 * `scale` the CSS pixels to one unit (the world's size at the map's zoom). The
 * map is never tilted or turned, so a distance in Mercator is one on the
 * screen. Only the one found is named: a metro's lights at the national view
 * are hundreds within a finger's reach.
 */
export function nearestLit(
  lit: LitSpots,
  at: { readonly x: number; readonly y: number },
  scale: number,
  radius: number,
): SchoolHit | null {
  const points = mercator(lit);
  const reach = radius / scale;
  let nearest = -1;
  let best = Infinity;
  for (let i = 0; i < lit.ids.length; i++) {
    const dx = (points[i * 2] ?? Number.NaN) - at.x;
    const dy = (points[i * 2 + 1] ?? Number.NaN) - at.y;
    if (!(Math.abs(dx) <= reach && Math.abs(dy) <= reach)) continue;
    const distance = Math.hypot(dx, dy) * scale;
    if (distance <= radius && distance < best) {
      nearest = i;
      best = distance;
    }
  }
  const id = lit.ids[nearest];
  if (id === undefined) return null;
  return {
    id,
    name: shownName(id, lit.names[nearest] ?? ''),
    lon: lit.lngLat[nearest * 2] ?? 0,
    lat: lit.lngLat[nearest * 2 + 1] ?? 0,
    distance: best,
  };
}

/** A school a feature of the school layers is (schools.ts reads the same properties), or null. */
function featureSchool(feature: {
  readonly properties: Record<string, unknown>;
  readonly geometry: unknown;
}): Omit<SchoolHit, 'distance'> | null {
  const { id, name } = feature.properties;
  const geometry = feature.geometry as { type?: unknown; coordinates?: unknown };
  if (typeof id !== 'string' || geometry.type !== 'Point') return null;
  const [lon, lat] = Array.isArray(geometry.coordinates) ? (geometry.coordinates as unknown[]) : [];
  if (typeof lon !== 'number' || typeof lat !== 'number') return null;
  return { id, name: typeof name === 'string' ? name : '', lon, lat };
}

/** The school the pointer at `point` (CSS pixels on the map) means, within `radius`, or null. */
export function schoolAt(
  map: MapLibreMap,
  point: { readonly x: number; readonly y: number },
  radius: number,
  lit: LitSpots | null,
): SchoolHit | null {
  const hits: SchoolHit[] = [];
  const { schoolDots, schoolNames } = BASEMAP_IDS;
  const layers = [schoolDots, schoolNames].filter((id) => map.getLayer(id) !== undefined);
  if (layers.length > 0) {
    const box: [PointLike, PointLike] = [
      [point.x - radius, point.y - radius],
      [point.x + radius, point.y + radius],
    ];
    /** The schools whose names are under the pointer itself, asked for once a name is near. */
    let named: Set<SchoolId> | null = null;
    for (const feature of map.queryRenderedFeatures(box, { layers })) {
      const school = featureSchool(feature);
      if (school === null) continue;
      if (feature.layer.id === schoolNames) {
        named ??= new Set(
          map
            .queryRenderedFeatures([point.x, point.y], { layers: [schoolNames] })
            .flatMap((under) => featureSchool(under)?.id ?? []),
        );
        hits.push({ ...school, distance: named.has(school.id) ? 0 : radius });
        continue;
      }
      const at = map.project([school.lon, school.lat]);
      hits.push({ ...school, distance: Math.hypot(at.x - point.x, at.y - point.y) });
    }
  }
  if (lit !== null && lit.ids.length > 0) {
    const { lng, lat } = map.unproject([point.x, point.y]);
    const at = { x: mercatorXFromLng(lng), y: mercatorYFromLat(lat) };
    const hit = nearestLit(lit, at, TILE * 2 ** map.getZoom(), radius);
    if (hit !== null) hits.push(hit);
  }
  return nearestSchool(hits, radius);
}

export interface SchoolTapOptions {
  /** The schools the glow lights now, or null for none. */
  readonly lit: () => LitSpots | null;
  /** A school was clicked or tapped: open it. */
  readonly onSchool: (school: SchoolHit) => void;
}

/** A click, as the next one is measured against. */
interface Click {
  readonly time: number;
  readonly x: number;
  readonly y: number;
  /** Whether it opened a school. */
  opened: boolean;
}

/**
 * Opens the school a click or a tap on the map means, and shows a pointer
 * over one with a mouse. Returns the function that stops it.
 */
export function attachSchoolTaps(map: MapLibreMap, options: SchoolTapOptions): () => void {
  const container = map.getCanvasContainer();
  /** The type of the pointer that last pressed on the map. */
  let pointerType = 'mouse';
  let last: Click | null = null;
  let pending: number | undefined;
  /** True while two fingers or more are on the map. */
  let pinching = false;
  /** When the map was last pressed, moved by hand or turned by a wheel, as an event's timeStamp. */
  let touched = -Infinity;

  const cancel = (): void => {
    window.clearTimeout(pending);
    pending = undefined;
  };
  /** A press, a hand moving the map or a wheel: a click waiting to open a school opens none. */
  const interrupt = (event: { readonly originalEvent?: Event | undefined }): void => {
    // A move without an event is the map's own (a flight).
    const time = event.originalEvent?.timeStamp;
    if (time === undefined) return;
    touched = Math.max(touched, time);
    cancel();
  };
  /** Whether a press or a click at this time and place is the second of a double click on `click`. */
  const secondOf = (click: Click | null, time: number, x: number, y: number): boolean =>
    click !== null &&
    time - click.time >= 0 &&
    time - click.time < DOUBLE_TAP_MS &&
    Math.hypot(x - click.x, y - click.y) < DOUBLE_TAP_PX;

  const onPointerDown = (event: PointerEvent): void => {
    pointerType = event.pointerType;
  };
  const onClick = (event: MapMouseEvent): void => {
    const { originalEvent, point } = event;
    const time = originalEvent.timeStamp;
    // The second click of a double click, or a third: the map zooms, and nothing opens.
    if (originalEvent.detail > 1 || secondOf(last, time, point.x, point.y)) return;
    // Nor while fingers pinch, or for a click older than a press after it (a busy page's).
    if (pinching || touched > time) return;
    const click: Click = { time, x: point.x, y: point.y, opened: false };
    last = click;
    cancel();
    const type =
      'pointerType' in originalEvent && typeof originalEvent.pointerType === 'string'
        ? originalEvent.pointerType
        : '';
    const school = schoolAt(map, point, hitRadius(type || pointerType), options.lit());
    if (school === null) return;
    pending = window.setTimeout(() => {
      pending = undefined;
      click.opened = true;
      options.onSchool(school);
    }, OPEN_AFTER_MS);
  };
  // The second click of a double click whose first already opened a school: the pick's flight goes on.
  const onDoubleClick = (event: MapMouseEvent): void => {
    const { originalEvent, point } = event;
    if (last?.opened === true && secondOf(last, originalEvent.timeStamp, point.x, point.y)) {
      event.preventDefault();
    }
  };
  const onTouchStart = (event: MapTouchEvent): void => {
    interrupt(event);
    const { originalEvent, point } = event;
    if (originalEvent.touches.length > 1) {
      pinching = true;
      return;
    }
    // The same for a double tap.
    if (last?.opened === true && secondOf(last, originalEvent.timeStamp, point.x, point.y)) {
      event.preventDefault();
    }
  };
  const onTouchEnd = (event: MapTouchEvent): void => {
    if (event.originalEvent.touches.length === 0) pinching = false;
  };

  /** Where the mouse is over the map, or null when it is not. */
  let hover: { x: number; y: number } | null = null;
  let frame: number | undefined;
  let pointing = false;
  const point = (on: boolean): void => {
    if (on === pointing) return;
    pointing = on;
    container.classList.toggle(POINTER_CLASS, on);
  };
  const lookUnderMouse = (): void => {
    frame = undefined;
    point(hover !== null && schoolAt(map, hover, HIT_RADIUS.mouse, options.lit()) !== null);
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

  container.addEventListener('pointerdown', onPointerDown, { passive: true });
  map.on('click', onClick);
  map.on('dblclick', onDoubleClick);
  map.on('mousedown', interrupt);
  map.on('touchstart', onTouchStart);
  map.on('touchend', onTouchEnd);
  map.on('touchcancel', onTouchEnd);
  map.on('movestart', interrupt);
  map.on('wheel', interrupt);
  map.on('mousemove', onMouseMove);
  map.on('mouseout', onMouseOut);
  map.on('moveend', onMoveEnd);
  return () => {
    cancel();
    if (frame !== undefined) cancelAnimationFrame(frame);
    point(false);
    container.removeEventListener('pointerdown', onPointerDown);
    map.off('click', onClick);
    map.off('dblclick', onDoubleClick);
    map.off('mousedown', interrupt);
    map.off('touchstart', onTouchStart);
    map.off('touchend', onTouchEnd);
    map.off('touchcancel', onTouchEnd);
    map.off('movestart', interrupt);
    map.off('wheel', interrupt);
    map.off('mousemove', onMouseMove);
    map.off('mouseout', onMouseOut);
    map.off('moveend', onMoveEnd);
  };
}

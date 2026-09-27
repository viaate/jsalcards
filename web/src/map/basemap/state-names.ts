/**
 * State names, on a phone's map: quiet spaced capitals, each in its state's
 * widest open space, so the black country reads state by state on a small
 * screen without a lifted land. build-geo.mjs places them in the bundled
 * file, clear of the city names, and works out how large each fits there.
 * style.ts draws them in one layer, whose filter the map keeps to the names
 * that fit at its zoom (index.ts); home-names.ts keeps the screen's edges
 * from cutting them at the home view.
 */
import { OPENFREEMAP_MIN_ZOOM } from './openfreemap';
import { STATE_NAME_SIZE } from './us-geo';

export { STATE_NAME_LEADING, STATE_NAME_TRACKING } from './us-geo';

/**
 * A state's name, where the map puts it, the label it sets there (broken
 * over two lines where it fits larger so) and `fit`, the largest size in CSS
 * pixels at zoom 0 it fits inside its state at: fit * 2^z at zoom z.
 */
export interface StateName {
  readonly name: string;
  readonly label: string;
  readonly fit: number;
  readonly lon: number;
  readonly lat: number;
}

/** The bundled file, as far as the state names go: GeoJSON features. */
interface Features {
  readonly features: readonly unknown[];
}

/** The street map's own names take over at this zoom, where the bundled names stop. */
export const STATE_NAMES_UNTIL = OPENFREEMAP_MIN_ZOOM;

/** The state names in the bundled file, in its order. */
export function stateNamesOf(usLines: Features): StateName[] {
  const names: StateName[] = [];
  for (const feature of usLines.features) {
    const { properties, geometry } = (feature ?? {}) as {
      properties?: { kind?: unknown; name?: unknown; label?: unknown; fit?: unknown };
      geometry?: { type?: unknown; coordinates?: unknown };
    };
    if (properties?.kind !== 'state-name' || geometry?.type !== 'Point') continue;
    const { name, label, fit } = properties;
    const [lon, lat]: readonly unknown[] = Array.isArray(geometry.coordinates)
      ? (geometry.coordinates as readonly unknown[])
      : [];
    if (typeof name !== 'string' || typeof label !== 'string') continue;
    if (typeof fit !== 'number' || !(fit > 0)) continue;
    if (typeof lon !== 'number' || typeof lat !== 'number') continue;
    names.push({ name, label, fit, lon, lat });
  }
  return names;
}

/** A state name's size in CSS pixels at `zoom`, as the style sets it and build-geo.mjs fitted it. */
export function stateNameSize(zoom: number): number {
  const { fromZoom, from, toZoom, to } = STATE_NAME_SIZE;
  return from + (to - from) * Math.min(1, Math.max(0, (zoom - fromZoom) / (toZoom - fromZoom)));
}

/**
 * The zoom a state is first named at: the first, in hundredths, at which its
 * name set at stateNameSize fits inside it, and never before the size's first
 * zoom. Its size grows slower than the map, so it fits from there on.
 */
export function stateNameFrom(fit: number): number {
  const fits = (zoom: number): boolean => stateNameSize(zoom) <= fit * 2 ** zoom;
  let low: number = STATE_NAME_SIZE.fromZoom;
  if (fits(low)) return low;
  let high = STATE_NAMES_UNTIL;
  if (!fits(high)) return Infinity;
  while (high - low > 1e-4) {
    const middle = (low + high) / 2;
    if (fits(middle)) high = middle;
    else low = middle;
  }
  return Math.ceil(high * 100) / 100;
}

/** Whether the map names a state of `fit` at `zoom`: from the zoom its name fits at, until the handover. */
export function stateNameShown(fit: number, zoom: number): boolean {
  return zoom >= stateNameFrom(fit) && zoom < STATE_NAMES_UNTIL;
}

/** A state's name, with the zoom the map names it from. */
export type NamedState = StateName & { readonly from: number };

/** The states the map names at some zoom before the handover, each with the zoom it starts at. */
export function namedStates(states: readonly StateName[]): NamedState[] {
  return states
    .map((state) => ({ ...state, from: stateNameFrom(state.fit) }))
    .filter((state) => state.from < STATE_NAMES_UNTIL);
}

/** The names of the states the map names at `zoom`, in their order, less those in `hidden`. */
export function stateNamesAt(
  states: readonly NamedState[],
  zoom: number,
  hidden: readonly string[] = [],
): string[] {
  if (!(zoom < STATE_NAMES_UNTIL)) return [];
  return states
    .filter((state) => zoom >= state.from && !hidden.includes(state.name))
    .map((state) => state.name);
}

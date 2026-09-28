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
import { STATE_NAME_SIZE, STATE_NAME_SMALL } from './us-geo';

export { STATE_NAME_LEADING, STATE_NAME_TRACKING } from './us-geo';

/**
 * A state's name, where the map puts it, the label it sets there (broken
 * over two lines where it fits larger so) and `fit`, the largest size in CSS
 * pixels at zoom 0 it fits inside its state at: fit * 2^z at zoom z. Where
 * build-geo.mjs found it clear of the city names only at the small size,
 * `usualFrom` is the zoom its usual size is clear of them from.
 */
export interface StateName {
  readonly name: string;
  readonly label: string;
  readonly fit: number;
  readonly lon: number;
  readonly lat: number;
  readonly usualFrom?: number;
}

/** The bundled file, as far as the state names go: GeoJSON features. */
interface Features {
  readonly features: readonly unknown[];
}

/** The street map's own names take over at this zoom, where the bundled names stop. */
export const STATE_NAMES_UNTIL = OPENFREEMAP_MIN_ZOOM;

/**
 * A state whose name fits inside it only at a smaller size, or is clear of
 * the city names only so, is named at that size, STATE_NAME_SMALL of the
 * usual one (placed so by build-geo.mjs), from the zoom it fits at: so a
 * phone's opening view names every state it shows whole enough to hold a
 * name (Pennsylvania, North Carolina at zoom 3.85), each still inside its
 * state. Its usual size takes over from the zoom that fits, clear.
 */
export { STATE_NAME_SMALL } from './us-geo';

/** The state names in the bundled file, in its order. */
export function stateNamesOf(usLines: Features): StateName[] {
  const names: StateName[] = [];
  for (const feature of usLines.features) {
    const { properties, geometry } = (feature ?? {}) as {
      properties?: {
        kind?: unknown;
        name?: unknown;
        label?: unknown;
        fit?: unknown;
        usualFrom?: unknown;
      };
      geometry?: { type?: unknown; coordinates?: unknown };
    };
    if (properties?.kind !== 'state-name' || geometry?.type !== 'Point') continue;
    const { name, label, fit, usualFrom } = properties;
    const [lon, lat]: readonly unknown[] = Array.isArray(geometry.coordinates)
      ? (geometry.coordinates as readonly unknown[])
      : [];
    if (typeof name !== 'string' || typeof label !== 'string') continue;
    if (typeof fit !== 'number' || !(fit > 0)) continue;
    if (typeof lon !== 'number' || typeof lat !== 'number') continue;
    names.push({
      name,
      label,
      fit,
      lon,
      lat,
      ...(typeof usualFrom === 'number' ? { usualFrom } : {}),
    });
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
 * name set at stateNameSize (times `scale`) fits inside it, and never before
 * the size's first zoom. Its size grows slower than the map, so it fits from
 * there on.
 */
export function stateNameFrom(fit: number, scale = 1): number {
  const fits = (zoom: number): boolean => scale * stateNameSize(zoom) <= fit * 2 ** zoom;
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

/**
 * Whether the map names a state of `fit` at `zoom`: from the zoom its name
 * fits at, at the small size or the usual one, until the handover.
 */
export function stateNameShown(fit: number, zoom: number): boolean {
  return zoom >= stateNameFrom(fit, STATE_NAME_SMALL) && zoom < STATE_NAMES_UNTIL;
}

/**
 * The zoom a state is named at its usual size from: where that fits, and is
 * clear of the city names (StateName usualFrom).
 */
export function stateNameUsualFrom(state: Pick<StateName, 'fit' | 'usualFrom'>): number {
  return Math.max(stateNameFrom(state.fit), state.usualFrom ?? -Infinity);
}

/**
 * The size a state is named at, at `zoom`: its usual size, or the small one
 * where only that fits or is clear of the city names.
 */
export function stateNameSizeFor(
  state: Pick<StateName, 'fit' | 'usualFrom'>,
  zoom: number,
): number {
  const scale = zoom >= stateNameUsualFrom(state) ? 1 : STATE_NAME_SMALL;
  return scale * stateNameSize(zoom);
}

/** A state's name, with the zooms the map names it from: at the small size, and at the usual one. */
export type NamedState = StateName & { readonly from: number; readonly fromSmall: number };

/** The states the map names at some zoom before the handover, each with the zooms it starts at. */
export function namedStates(states: readonly StateName[]): NamedState[] {
  return states
    .map((state) => ({
      ...state,
      from: stateNameUsualFrom(state),
      fromSmall: stateNameFrom(state.fit, STATE_NAME_SMALL),
    }))
    .filter((state) => state.fromSmall < STATE_NAMES_UNTIL);
}

/** The names of the states the map names at `zoom`, at either size, in their order, less those in `hidden`. */
export function stateNamesAt(
  states: readonly NamedState[],
  zoom: number,
  hidden: readonly string[] = [],
): string[] {
  if (!(zoom < STATE_NAMES_UNTIL)) return [];
  return states
    .filter((state) => zoom >= state.fromSmall && !hidden.includes(state.name))
    .map((state) => state.name);
}

/** Of those, the ones named at the small size at `zoom`: their name fits only so. */
export function smallStateNamesAt(
  states: readonly NamedState[],
  zoom: number,
  hidden: readonly string[] = [],
): string[] {
  if (!(zoom < STATE_NAMES_UNTIL)) return [];
  return states
    .filter((state) => zoom >= state.fromSmall && zoom < state.from && !hidden.includes(state.name))
    .map((state) => state.name);
}

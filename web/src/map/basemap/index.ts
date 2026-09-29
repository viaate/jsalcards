import type {
  FilterSpecification,
  GeoJSONSource,
  LayerSpecification,
  Map as MapLibreMap,
  MapMouseEvent,
  MapMovementEvent,
  MapTouchEvent,
  TransformConstrainFunction,
} from 'maplibre-gl';
import { DATA_FILES } from 'virtual:snowlight/data-files';

import { mapLocale } from '../../copy';
import { DATA_PATHS, createDataFiles, dataRootFor } from '../../data/files';
import { mercatorXFromLng, mercatorYFromLat } from '../glow/mercator';
import { collapsedAttribution } from './attribution';
import { prepareCanvas, warmFirstPrograms, warmTilePrograms, withCanvas } from './warm-up';
import { workerCount } from './workers';
import { CONTROL_CLEARANCE, keepLabelsClear } from './clearance';
import { cityNamesOf, namesCutByEdges, stateNamesCutByEdges, textMeasure } from './home-names';
import { addMapFonts } from './fonts';
import type { MapLibre } from './maplibre';
import type { WorkerUrls } from './maplibre-worker';
import {
  OPENFREEMAP_ATTRIBUTION,
  OPENFREEMAP_MAX_ZOOM,
  OPENFREEMAP_MIN_ZOOM,
  prefetchOpenFreeMapTiles,
} from './openfreemap';
import { MAX_ZOOM } from './bounds';
import type { MapView } from './bounds';
import { constrainView, viewLimits } from './limits';
import type { Insets, Place, Size, ViewLimits } from './limits';
import {
  FLIGHT_DEADLINE_MS,
  FLIGHT_HOLD_MS,
  FLIGHT_LAST_CALL_MS,
  FLIGHT_LEAD,
  FLIGHT_MS_PER_ZOOM,
  FLIGHT_STOP_ZOOM,
  coverPoints,
  flightCeiling,
  flightEasing,
  holdVerdict,
  pacedProgress,
  progressAt,
  streetTileZoom,
} from './flight';
import type { HoldVerdict, LoadedTile } from './flight';
import { failedTiles, healTiles, styleOf } from './heal';
import { heldFrame } from './held-frame';
import { maskFeed as createMaskFeed } from './mask/feed';
import { flightTileLimit, flightTiles, slowLink } from './prefetch';
import { insideUs } from './us-inside';
import { afterNextFrame, LIVE_CLASS, markStep, whenGpuIdle, yieldToMain } from './reveal';
import { SCHOOL_SPACE_IMAGE, schoolSpaceImage, selectedSchoolFilter } from './schools';
import { STATE_AREAS_UNTIL, keptNames, nameBox, parseStateAreas, stateSpots } from './state-areas';
import type { ScreenRect, SetName, StateArea } from './state-areas';
import {
  STATE_NAME_LEADING,
  STATE_NAME_SMALL,
  STATE_NAME_TRACKING,
  namedStates,
  smallStateNamesAt,
  stateNameSize,
  stateNameSizeFor,
  stateNamesAt,
  stateNamesOf,
} from './state-names';
import {
  BASEMAP_IDS,
  BUNDLED_LINES_UNTIL,
  CITY_NAME_BANDS,
  CITY_NAME_PADDING,
  CITY_NAME_PHONE_PADDING,
  STATE_NAME_PADDING,
  buildBasemapStyle,
  cityNameSize,
  cityNameFilter,
  cityNameLayerId,
  stageStyle,
  stateNameFilter,
  stateNameSizeExpression,
} from './style';
import type { BasemapLook, UsLinesData } from './style';
import { STATE_NAME_SIZE, US_BOUNDS } from './us-geo';
import { US_MASK_FILE } from './us-mask';
import { US_MASK_ALIAS } from './us-mask-alias';

export { BASEMAP_IDS } from './style';
export { FLIGHT_STOP_ZOOM } from './flight';
// How a school's dot and name are drawn at a zoom, for a click on them (map/school-taps.ts).
export { schoolDotOpacity, schoolDotRadius, schoolNameOpacity } from './schools';
export { US_BOUNDS } from './us-geo';
export type { MapView } from './bounds';
export type { Place, ViewLimits } from './limits';

export interface BasemapOptions {
  /** Element the map fills. */
  container: HTMLElement;
  /**
   * Element whose box the continental US is fitted into at the national view.
   * The inline still in index.html is laid out on the same box by the same
   * rules, which is what makes the handover invisible.
   */
  frame: HTMLElement;
  /**
   * The viewer's own place, when a phone knows it: the home view is then
   * their area, at NEARBY_ZOOM (limits.ts), instead of the national view.
   */
  near?: Place | null;
  /**
   * A view to open at instead of the home view, such as one from a link.
   * The map opens at the nearest view its limits allow.
   */
  view?: MapView | null;
  /**
   * The page's controls over the map (the search field, the legend and the
   * like): the map's labels keep clear of them (clearance.ts), as of its
   * own attribution button.
   */
  controls?: () => Iterable<Element>;
  /**
   * Runs once, in the task that first shows the canvas, just before it does.
   * `national` says whether the map is at the national view, the one the
   * inline still draws: when it is not (a link's view, the viewer's area, or
   * a flight or a hand already on the move), the page takes the still away
   * here, so the country is never laid over a street.
   */
  onReveal?: (reveal: { national: boolean }) => void;
}

/** What load.ts fetched in parallel before the map is created. */
export interface BasemapResources {
  /** The MapLibre module. */
  maplibre: MapLibre;
  /** URL MapLibre starts its workers from (maplibre-worker.ts). */
  workerUrl: string;
  /** The bundled continental US lines' city and state names, already fetched and parsed. */
  usNames: UsLinesData;
  /** Where the map's GeoJSON sources read the lines and the names from (style.ts). */
  usLinesUrls: { readonly lines: string; readonly names: string };
  /** The school tiles' archive this build ships, as an absolute URL, or null. */
  schools: string | null;
  /** The states' shapes a phone names the states in view by (state-areas.ts), fetched when first needed. */
  stateAreas?: string;
  /**
   * The US mask archive the street tiles are cut by (street-tiles.ts), as
   * this page reads it; pageMask() unless told otherwise. Fetched once street
   * tiles near a border or a coast are needed, or about to be
   * (prepareStreets): never on a plain visit, nor for streets wholly inside
   * the US.
   */
  mask?: PageMask;
}

export interface Basemap {
  readonly map: MapLibreMap;
  /**
   * Resolves once the canvas is on screen: at the national view after its
   * first complete frame, and at any other view once it has drawn that view
   * (the street tiles across the screen), or by LINK_REVEAL_MS after the map
   * is created; at once when someone moves the map.
   */
  readonly ready: Promise<void>;
  /** True once someone has moved the map. */
  readonly moved: boolean;
  /**
   * True while the map shows the home view, which it keeps fitted to the
   * frame as the window resizes: from the start (unless it opened at a given
   * view) and after showHome, until someone moves the map.
   */
  readonly national: boolean;
  /** Where the map is now. */
  readonly view: MapView;
  /**
   * True while a flight into streets is on its way, short of where it is
   * going: at its stop over its destination, gliding in, or waiting on the
   * way in for the street tiles (flight.ts). The view is on the way, not
   * where the map is going.
   */
  readonly flightStopped: boolean;
  /** How far the map zooms out and pans on this screen; they follow the window's size. */
  readonly limits: ViewLimits;
  /**
   * Places the labels again, clear of the page's controls as they are now:
   * for a control that has just appeared over the map.
   */
  controlsChanged(): void;
  /** Goes to the home view, as at the start: the country fitted into the frame, or the viewer's area. */
  showHome(options?: { animate?: boolean }): void;
  /**
   * Makes the area around `place` the home view, and glides there; false, and
   * nothing moves, for a place off the continental US.
   */
  showNear(place: Place): boolean;
  /** Rings the school with this id (its panel is open), or none with null. */
  selectSchool(id: string | null): void;
  /** Moves to the nearest view the limits allow, or to the home view with null. */
  goTo(view: MapView | null): void;
  /** Glides to the nearest view the limits allow; jumps when reduced motion is preferred. */
  flyTo(view: MapView): void;
  /**
   * Someone's search shows `place` first, or nothing (no `place`): once it
   * has stayed first for RESULT_SETTLE_MS (not for each letter typed) with
   * the map sent nowhere meanwhile, they are probably on their way to its
   * streets, and what the street tiles there need before any can be drawn
   * comes, the US mask, unless a flight there would ask for none but tiles
   * wholly inside the US (us-inside.ts), which need none. Pressing on a
   * school asks the same, at once.
   */
  prepareStreets(place?: Place): void;
  /** Glides to show [west, south, east, north] inside the frame, no closer than `maxZoom`. */
  fitBounds(
    bounds: readonly [number, number, number, number],
    options?: { maxZoom?: number },
  ): void;
  destroy(): void;
}

/**
 * How far past the screen's edges, as a share of its size, a view may reach
 * and still be glided to from the streets on screen: the tiles drawn reach
 * a little past the edges.
 */
export const ON_SCREEN_MARGIN = 0.125;

/** MapLibre's size for a container that has none yet. */
const FALLBACK_SIZE: Size = { width: 400, height: 300 };

/**
 * The sources a flight asks for tiles of only where it stops and where it
 * ends, not at each zoom it passes on the way: the street tiles and the
 * school tiles, which come over the network.
 */
const HELD_IN_FLIGHT = [BASEMAP_IDS.openFreeMapSource, BASEMAP_IDS.schoolsSource] as const;

/**
 * How long past its own duration a glide may hold them, in milliseconds,
 * whatever becomes of it.
 */
const GLIDE_HOLD_SLACK_MS = 2000;

const NO_PADDING: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

/**
 * How long each turn of adding the style's layers after it is in (style.ts
 * stageStyle) may run, in milliseconds, before the page gets the main thread
 * back.
 */
const LAYER_TURN_MS = 4;

/** Style changes made here go in as built: style.test.ts checks every layer against the spec. */
const NOT_CHECKED = { validate: false } as const;

/**
 * A view other than the national one (a link's, or the viewer's area) is not
 * what the inline still shows: the map is shown in its place once it has
 * drawn the view, and by this long after it is created whatever it has, so a
 * slow tile never keeps the whole country standing in for a street for long.
 */
export const LINK_REVEAL_MS = 4000;

/**
 * How far a state's name as measured here may run past the box MapLibre
 * sets it in, in CSS pixels: the room kept on top of the clear space the
 * map keeps between its labels and around the page's controls.
 */
const LABEL_SLACK = 2;

/** A state's name in the source of the states-in-view layer, set `scale` times the usual size. */
interface StateAreaFeature {
  readonly type: 'Feature';
  readonly properties: { readonly name: string; readonly label: string; readonly scale: number };
  readonly geometry: { readonly type: 'Point'; readonly coordinates: [number, number] };
}

declare global {
  interface Window {
    /** The map, for end-to-end tests: set only when navigator.webdriver is true. */
    snowlightMap?: MapLibreMap;
  }
}

let configured: MapLibre | undefined;

/**
 * MapLibre's global settings; they must be in place before the first map
 * starts its workers. Street tiles load in the workers, which cut them to the
 * US (street-tiles.ts); the page only asks for them ahead of a flight, to have
 * them cached (prefetch.ts).
 */
function configure(maplibre: MapLibre, workerUrl: string): void {
  if (configured === maplibre) return;
  maplibre.setWorkerUrl(workerUrl);
  maplibre.setWorkerCount(workerCount(navigator.hardwareConcurrency));
  configured = maplibre;
}

/**
 * The US mask as this page reads it (mask/feed.ts): its URL, the URL of its
 * copy under a name that never changes, and the channel the page sends it to
 * its workers on, this page's own, so another tab's workers are not asked.
 */
export interface PageMask {
  readonly url: string;
  readonly fallbackUrl: string;
  readonly channel: string;
}

let thisPageMask: PageMask | undefined;

/** This page's mask: made once, for its workers and its map alike. */
export function pageMask(): PageMask {
  const file = (path: string): string =>
    new URL(`${import.meta.env.BASE_URL}${path}`, document.baseURI).href;
  thisPageMask ??= {
    url: file(US_MASK_FILE),
    fallbackUrl: file(US_MASK_ALIAS),
    channel: `snowlight-mask-${Math.random().toString(36).slice(2)}`,
  };
  return thisPageMask;
}

/**
 * Starts MapLibre's workers ahead of the map, so they load MapLibre's shared
 * module while the map is being created rather than after: from the worker
 * source `workerUrl` makes of the chunks the workers import (MapLibre's
 * shared module, the street and the school tiles), and this page's mask.
 * Returns the worker's URL.
 */
export function startWorkers(
  maplibre: MapLibre,
  workerUrl: (sources: WorkerUrls) => string,
  shared: { readonly SHARED_URL: string },
  streetTiles: { readonly STREET_TILES_URL: string },
  schoolTiles: { readonly SCHOOL_TILES_URL: string },
): string {
  const { url: mask, channel: maskChannel } = pageMask();
  const worker = workerUrl({
    shared: shared.SHARED_URL,
    streetTiles: streetTiles.STREET_TILES_URL,
    schoolTiles: schoolTiles.SCHOOL_TILES_URL,
    mask,
    maskChannel,
  });
  configure(maplibre, worker);
  maplibre.prewarm();
  return worker;
}

/** The school tiles' archive this build ships, as an absolute URL, or null when it ships none. */
export function schoolTilesArchive(
  paths: readonly string[] = DATA_FILES,
  base: string = import.meta.env.BASE_URL,
): string | null {
  return createDataFiles(paths, dataRootFor(base, document.baseURI)).url(DATA_PATHS.schoolTiles);
}

/** Padding that places the fitted bounds exactly inside the frame. */
export function framePadding(container: Element, frame: Element): Insets {
  const outer = container.getBoundingClientRect();
  const inner = frame.getBoundingClientRect();
  return {
    top: Math.max(0, inner.top - outer.top),
    right: Math.max(0, outer.right - inner.right),
    bottom: Math.max(0, outer.bottom - inner.bottom),
    left: Math.max(0, inner.left - outer.left),
  };
}

/** The names left out at the home view: the ones the screen's edges would cut. */
interface HiddenNames {
  readonly cities: readonly string[];
  readonly states: readonly string[];
}

const NONE_HIDDEN: HiddenNames = Object.freeze({ cities: [], states: [] });

/**
 * How often, at most, the state names follow a zoom in progress, in
 * milliseconds; they catch up exactly when it ends.
 */
const STATE_NAMES_REFRESH_MS = 120;

/**
 * How long, in milliseconds, a search's first place stays first before the
 * streets there are prepared for (prepareStreets): long enough that a place
 * shown on the way to another, as someone types, asks for nothing.
 */
const RESULT_SETTLE_MS = 500;

/** Whether two lists of names are the same, in the same order. */
function sameNames(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((name, i) => name === b[i]);
}

/** A design token's value, or `fallback` when the page has none. */
function tokenReader(): (name: string, fallback: string) => string {
  const style = getComputedStyle(document.documentElement);
  return (name, fallback) => {
    const value = style.getPropertyValue(name).trim();
    return value === '' ? fallback : value;
  };
}

/** Whether the page asks for names set for a phone: --map-names is "phone" there. */
function phoneNamesWanted(token = tokenReader()): boolean {
  return token('--map-names', '') === 'phone';
}

/**
 * Line colors and width come from the same CSS custom properties that draw the
 * inline still, so the two cannot drift apart; label and building tones come
 * from the design tokens the rest of the page uses.
 */
function look(): BasemapLook {
  const token = tokenReader();
  const hairline = Number.parseFloat(token('--hairline', '1px'));
  return {
    hairline: Number.isFinite(hairline) && hairline > 0 ? hairline : 1,
    phoneNames: phoneNamesWanted(token),
    colors: {
      background: token('--bg', '#000'),
      land: token('--land', '#000'),
      outline: token('--line-outline', '#6b6b6b'),
      state: token('--line-state', '#2a2a2a'),
      label: token('--text-2', '#a3a3a3'),
      labelDim: token('--text-3', '#6b6b6b'),
      labelBright: token('--text-1', '#f5f5f5'),
      building: token('--surface-2', '#111'),
      buildingEdge: token('--border-1', '#1f1f1f'),
    },
  };
}

/**
 * Creates the WebGL basemap from what load.ts fetched: the style is built in
 * one task and the map created in the next, as each is sizable work on the
 * page's main thread. `ready` resolves once the map is on screen.
 */
export async function createBasemap({
  container,
  frame,
  view = null,
  near: nearAtStart = null,
  controls,
  onReveal,
  maplibre,
  workerUrl,
  usNames,
  usLinesUrls,
  schools,
  stateAreas: stateAreasUrl,
  mask = pageMask(),
}: BasemapOptions & BasemapResources): Promise<Basemap> {
  configure(maplibre, workerUrl);
  addMapFonts();
  const bounds = new maplibre.LngLatBounds(
    [US_BOUNDS[0], US_BOUNDS[1]],
    [US_BOUNDS[2], US_BOUNDS[3]],
  );

  // The screen as MapLibre measures it, and the frame's insets within it.
  const size = (): Size => ({
    width: Math.floor(container.clientWidth) || FALLBACK_SIZE.width,
    height: Math.floor(container.clientHeight) || FALLBACK_SIZE.height,
  });
  const fitPadding = (): Insets => {
    const padding = framePadding(container, frame);
    const { width, height } = size();
    // A frame with no area (a very short window): fit the whole screen instead, as the limits do.
    return width - padding.left - padding.right > 0 && height - padding.top - padding.bottom > 0
      ? padding
      : NO_PADDING;
  };
  /** The viewer's place, whose area is the home view, or null for the national view. */
  let near: Place | null = nearAtStart;
  let limits = viewLimits(size(), fitPadding(), near);
  /** Whether the home view is the national view, which MapLibre's own fitBounds places. */
  const homeIsNational = (): boolean => limits.home === limits.fit;
  /** MapLibre runs this on every change of view: wheel, drag, pinch, keys, animations, resizes. */
  const constrainer =
    (current: ViewLimits): TransformConstrainFunction =>
    (lngLat, zoom) => {
      const allowed = constrainView(current, { lat: lngLat.lat, lon: lngLat.lng, zoom });
      return {
        center:
          allowed.lat === lngLat.lat && allowed.lon === lngLat.lng
            ? lngLat
            : new maplibre.LngLat(allowed.lon, allowed.lat),
        zoom: allowed.zoom,
      };
    };
  const start = view === null ? null : constrainView(limits, view);

  // At the home view, the names the screen's edges would cut are left out (home-names.ts).
  const cities = cityNamesOf(usNames);
  const states = namedStates(stateNamesOf(usNames));
  const measure = textMeasure();
  const initialLook = look();
  /** Whether the names are set for a phone, as the page says; it can change as the window does. */
  let phoneNames = initialLook.phoneNames === true;
  const cutAtHome = (): HiddenNames => ({
    cities: namesCutByEdges(cities, limits.home, size(), measure),
    states: phoneNames ? stateNamesCutByEdges(states, limits.home, size(), measure) : [],
  });
  let hiddenNames: HiddenNames = start === null ? cutAtHome() : NONE_HIDDEN;
  /** The state names the map draws now: the ones that fit at its zoom, less those left out. */
  let drawnStates: readonly string[] = phoneNames
    ? stateNamesAt(states, (start ?? limits.home).zoom, hiddenNames.states)
    : [];
  /** Of those, the ones drawn at the small size. */
  let smallStates: readonly string[] = phoneNames
    ? smallStateNamesAt(states, (start ?? limits.home).zoom, hiddenNames.states)
    : [];

  /**
   * The bundled names the layer's filter lets through: the ones that fit at
   * the map's zoom, until the states in view are named at rest; from then on
   * only those in `bundledKept`.
   */
  let filteredStates: readonly string[] = drawnStates;
  /**
   * Null while the states-in-view layer names no state (refreshStateAreas):
   * the bundled layer names every state that fits. Once that layer names the
   * states in view it names every state the map names, and the bundled layer
   * none, but for a moment the ones in here: each drawn by both at the same
   * spot, the same size, until that layer's names are on screen, so a name
   * is never missing as one layer hands it to the other (where two names
   * meet MapLibre draws the first, and that layer is placed first).
   */
  let bundledKept: ReadonlySet<string> | null = null;

  // The map starts with its style's sources and the ground, and takes on the layers a few at a
  // time once that is in: the ones its view draws, then the rest, or all at once if the camera
  // moves first. Each layer is MapLibre's work on the page's main thread (style.ts stageStyle).
  // The names are set above, the style built below and staged after it, each in a task of its own.
  await yieldToMain();
  const style = buildBasemapStyle({
    usLines: usNames,
    usLinesUrls,
    schools,
    hiddenCityNames: hiddenNames.cities,
    stateNames: drawnStates,
    smallStateNames: smallStates,
    ...initialLook,
  });
  await yieldToMain();
  const staged = stageStyle(style, (start ?? limits.home).zoom);
  await yieldToMain();
  // Its canvas and WebGL context first, in tasks of their own, then the map (warm-up.ts).
  const canvas = await prepareCanvas(size(), window.devicePixelRatio);
  await yieldToMain();
  const map = withCanvas(
    canvas,
    () =>
      new maplibre.Map({
        container,
        // No style yet: it goes on in a task of its own (below).
        locale: mapLocale,
        // At the national view, limits.fit is where MapLibre's fitBounds would put the country
        // (limits.ts), without the work of an animation of no length.
        center: [(start ?? limits.home).lon, (start ?? limits.home).lat],
        zoom: (start ?? limits.home).zoom,
        attributionControl: false,
        maplibreLogo: false,
        minZoom: limits.minZoom,
        maxZoom: MAX_ZOOM,
        transformConstrain: constrainer(limits),
        maxPitch: 0,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        renderWorldCopies: false,
        validateStyle: false,
        fadeDuration: 0,
        cancelPendingTileRequestsWhileZooming: true,
      }),
  );
  markStep('map-created');
  // Setting the map up goes in the task after its creation: each is sizable work.
  await yieldToMain();
  // The map is never tilted, so it never shows a horizon or a sky. MapLibre draws its sky in
  // every frame all the same, a pass over the whole screen, and builds its shader for the first.
  map.painter.drawFunctions = { ...map.painter.drawFunctions, sky: () => undefined };
  // A dot's space is made here the first time the style needs it: the style names no sprite.
  map.setMissingStyleImageResolver((id) => {
    if (map.hasImage(id)) return;
    if (id === SCHOOL_SPACE_IMAGE) map.addImage(SCHOOL_SPACE_IMAGE, schoolSpaceImage());
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  // The attribution button goes on once the style is in, in a task of its own: reading the
  // sources' attributions takes MapLibre a moment, and the button has nothing to show before.
  let attributed = false;
  const addAttribution = (): void => {
    if (attributed) return;
    attributed = true;
    map.addControl(
      collapsedAttribution(maplibre, { customAttribution: OPENFREEMAP_ATTRIBUTION }),
      'bottom-right',
    );
  };
  map.once('load', () => {
    window.setTimeout(addAttribution, 0);
  });

  /** The layers the map has yet to take on (style.ts stageStyle), in the order to add them. */
  const pendingLayers = [...staged.now, ...staged.later];
  /** How many of them its view draws from (stageStyle's `now`), all first. */
  let nowLeft = staged.now.length;
  /**
   * Adds the pending layers, each where the full style has it: before the
   * next layer after it that the map has. With a budget, it stops once that
   * many milliseconds have gone. Says whether any are left.
   *
   * MapLibre's own addLayer checks the layer against the whole style, which
   * it writes out again for each one, and draws a frame for each; here the
   * layers go on as built (style.test.ts checks the full style), and the map
   * takes them in with its next frame: the ones its view draws once they are
   * all on, and the rest once they are.
   */
  function addPendingLayers(budgetMs = Infinity): boolean {
    const started = performance.now();
    for (let layer = pendingLayers[0]; layer !== undefined; layer = pendingLayers[0]) {
      const at = staged.order.indexOf(layer.id);
      const before = staged.order.slice(at + 1).find((id) => map.getLayer(id) !== undefined);
      map.style.addLayer(layer, before, NOT_CHECKED);
      pendingLayers.shift();
      if (nowLeft > 0) nowLeft -= 1;
      const viewLayersOn = nowLeft === 0 && pendingLayers.length === staged.later.length;
      if (viewLayersOn || pendingLayers.length === 0) map._update(true);
      if (performance.now() - started >= budgetMs) break;
    }
    return pendingLayers.length > 0;
  }
  /** Changes a layer that has yet to go on the map (null) where it waits; else says where it is. */
  function changePending(
    id: string,
    change: (layer: LayerSpecification) => LayerSpecification,
  ): boolean {
    const index = pendingLayers.findIndex((layer) => layer.id === id);
    const layer = pendingLayers[index];
    if (layer === undefined) return false;
    pendingLayers[index] = change(layer);
    return true;
  }
  /** Sets a layer's filter, on the map or on the layer still to go on. */
  function setFilter(id: string, filter: FilterSpecification): void {
    if (!changePending(id, (layer) => ({ ...layer, filter }) as LayerSpecification)) {
      map.setFilter(id, filter, NOT_CHECKED);
    }
  }
  /** Sets one of a layer's layout properties, on the map or on the layer still to go on. */
  function setLayoutProperty(
    id: string,
    name: Parameters<MapLibreMap['setLayoutProperty']>[1],
    value: Parameters<MapLibreMap['setLayoutProperty']>[2],
  ): void {
    const changed = changePending(id, (layer) => ({
      ...layer,
      layout: { ...(layer as { layout?: object }).layout, [name]: value },
    }));
    if (!changed) map.setLayoutProperty(id, name, value, NOT_CHECKED);
  }
  // The programs its frames draw with, each built in a task of its own (warm-up.ts): the first
  // frame's once the style is in, and each tile's lines' and names' as the tile comes in.
  const inTaskOfItsOwn = (run: () => void): void => {
    window.setTimeout(run, 0);
  };
  map.once('style.load', () => {
    warmFirstPrograms(map, inTaskOfItsOwn);
  });
  const stopWarming = warmTilePrograms(map, inTaskOfItsOwn);
  /** Runs once every layer is on the map (the turns below). */
  let onAllLayers: (() => void) | null = null;
  /**
   * Once the style is in, adds the pending layers a turn at a time, each turn
   * a task of its own, from the one after the glow layer goes on (glow-mount.ts).
   */
  map.once('style.load', () => {
    const turn = (): void => {
      if (addPendingLayers(LAYER_TURN_MS)) {
        window.setTimeout(turn, 0);
        return;
      }
      const then = onAllLayers;
      onAllLayers = null;
      then?.();
    };
    window.setTimeout(turn, 0);
  });
  /**
   * Before the camera leaves the zoom the map opened at, every layer goes on
   * at once: the ones still to go on are drawn only at other zooms.
   */
  const needAllLayers = (): void => {
    if (pendingLayers.length === 0) return;
    try {
      addPendingLayers();
    } catch {
      // The style is still loading: its turns start once it is in.
    }
  };
  const onZoomAllLayers = (): void => {
    needAllLayers();
    if (pendingLayers.length === 0) map.off('zoom', onZoomAllLayers);
  };
  map.on('zoom', onZoomAllLayers);
  // No label runs under the page's controls, or under the attribution button.
  const clearance = keepLabelsClear(map, () => [
    ...(controls?.() ?? []),
    ...container.querySelectorAll('.maplibregl-ctrl'),
  ]);
  // End-to-end tests read what the map drew; only a browser under automation gets the handle.
  if (navigator.webdriver) window.snowlightMap = map;

  /** The view a cut leaves, held over the map until it has drawn the new one (held-frame.ts). */
  const held = heldFrame();
  /**
   * A flight keeps every tile it asks for loading until it arrives, instead of
   * dropping the ones the camera has zoomed past: each is drawn, scaled up,
   * until the closer ones are in, so the map shows streets all the way in.
   * Zooming by hand drops them again once the flight is over.
   *
   * From the country (the bundled lines) a flight into streets flies to a
   * stop over its destination at FLIGHT_STOP_ZOOM, where the bundled lines
   * still show. From streets, it glides to a view on the screen, and cuts to
   * one off it, whose way there crosses streets the map has none of: to its
   * destination FLIGHT_LEAD levels out (straight to it, where it takes in
   * the place the map is at), the view it leaves held on screen until the
   * map has drawn the new one (held-frame.ts). From the stop, and in a
   * glide, it goes in no further ahead of the street tiles on screen than
   * they can be drawn (flight.ts). No frame on the way is an empty black
   * screen.
   *
   * A flight ends where it was going unless someone moves the map or sends
   * it somewhere else: each leg of it (the flight to the stop, each glide)
   * ends in the next leg or at the destination, whatever ended it, and past
   * FLIGHT_DEADLINE_MS it waits for nothing (FLIGHT_LAST_CALL_MS: it is put
   * there).
   */
  let flights = 0;
  /** Moves someone made by hand, counted: a flight they interrupt goes no further. */
  let handMoves = 0;
  /** A flight is on its way, short of where it is going (Basemap flightStopped). */
  let stopped = false;
  /** The flight's watch on its deadlines (flyTo), cleared as it lands or gives way. */
  let deadline: number | undefined;
  /**
   * Whether the street and school tiles are held: asked for only where a
   * flight stops, not at every zoom a glide passes on its way (zoomIn).
   */
  let tilesHeld = false;
  /** Lets them go after a while, whatever becomes of the glide that held them. */
  let tilesHeldTimer: number | undefined;
  /**
   * Asks for the tiles the view needs again: the glide stopped, the flight is
   * over, or someone has the map.
   */
  const releaseTileRequests = (): void => {
    window.clearTimeout(tilesHeldTimer);
    if (!tilesHeld) return;
    tilesHeld = false;
    for (const id of HELD_IN_FLIGHT) styleOf(map)?.tileManagers[id]?.resume();
  };
  /**
   * Holds new street and school tile requests while a glide moves (MapLibre
   * pauses the sources), for at most `ms`.
   */
  const holdTileRequests = (ms: number): void => {
    const managers = styleOf(map)?.tileManagers;
    if (managers === undefined) return;
    tilesHeld = true;
    for (const id of HELD_IN_FLIGHT) managers[id]?.pause();
    window.clearTimeout(tilesHeldTimer);
    tilesHeldTimer = window.setTimeout(releaseTileRequests, ms);
  };
  /** Ends a flight on its way, where it is: the map is going somewhere else. */
  const cancelFlight = (): void => {
    flights++;
    window.clearTimeout(deadline);
    releaseTileRequests();
    held.release(false);
    stopped = false;
    map.cancelPendingTileRequestsWhileZooming = true;
  };
  /** Street and school tiles that fail are asked for again until they come (heal.ts). */
  const stopHealing = healTiles(map, [BASEMAP_IDS.openFreeMapSource, BASEMAP_IDS.schoolsSource]);
  /** The US mask: fetched once, on the way to the streets, sent to the workers (mask/feed.ts). */
  const maskFeed = createMaskFeed(mask.url, mask.channel, { fallbackUrl: mask.fallbackUrl });
  /** Whether street tiles need the mask: some are not wholly inside the US (us-inside.ts). */
  const needMask = (tiles: readonly (readonly [number, number, number])[]): boolean =>
    tiles.some(([z, x, y]) => !insideUs(z, x, y));
  /** Someone is on their way to the streets at `place`: the mask comes now, if they need it. */
  const streetsAhead = (place: Place): void => {
    // A flight there stops over it at the street tiles' first zoom: every tile it asks for is
    // under the ones covering the screen then. All wholly inside the US, it needs no mask.
    const over = flightTiles({ ...place, zoom: FLIGHT_STOP_ZOOM }, size(), FLIGHT_STOP_ZOOM);
    if (needMask(over)) maskFeed.start();
  };
  let resultTimer = 0;
  const prepareStreets = (place?: Place): void => {
    window.clearTimeout(resultTimer);
    if (place !== undefined) resultTimer = window.setTimeout(streetsAhead, RESULT_SETTLE_MS, place);
  };
  let moved = false;
  let national = start === null;
  /** Whether the map opens on the national view, the one the inline still draws. */
  const opensNational = start === null && homeIsNational();
  let live = false;
  let markReady: () => void = () => undefined;
  const ready = new Promise<void>((resolve) => {
    markReady = resolve;
  });
  const goLive = (): void => {
    if (live) return;
    live = true;
    // Where the map is now: at the national view unless it opened elsewhere or has moved off it.
    onReveal?.({ national: national && homeIsNational() && !map.isMoving() });
    container.classList.add(LIVE_CLASS);
    markStep('map-live');
    void afterNextFrame().then(markReady);
  };
  /** Shows the canvas once the GPU has drawn what it was given, so no half-drawn frame shows. */
  const goLiveWhenDrawn = (): void => {
    const gl = map.getCanvas().getContext('webgl2');
    if (gl === null) goLive();
    else void whenGpuIdle(gl).then(goLive);
  };
  map.once('load', () => {
    markStep('map-load');
  });
  // The national view shows once every layer is on and has drawn it, the still standing in
  // for it until then.
  if (opensNational) {
    onAllLayers = () => {
      const check = (): void => {
        if (live || !viewDrawn()) return;
        map.off('render', check);
        goLiveWhenDrawn();
      };
      map.on('render', check);
      map.triggerRepaint();
    };
  }
  // The still shows the whole country: a map opening anywhere else is shown in time, as a link's.
  const revealTimer = opensNational ? undefined : window.setTimeout(goLive, LINK_REVEAL_MS);

  /**
   * Leaves out these national city and state names, and brings back any other
   * left out before.
   */
  function hideNames(names: HiddenNames): void {
    const citiesChanged = !sameNames(names.cities, hiddenNames.cities);
    hiddenNames = names;
    if (citiesChanged) {
      whenStyled(() => {
        CITY_NAME_BANDS.forEach((_band, band) => {
          setFilter(cityNameLayerId(band), cityNameFilter(band, hiddenNames.cities));
        });
      });
    }
    refreshStateNames();
  }

  /**
   * Keeps the state names' one layer to the states whose names fit at the
   * map's zoom, less those left out (and, once the states in view are named,
   * to `bundledKept`): it changes only when the zoom crosses the zoom a
   * state's name fits at.
   */
  function refreshStateNames(): void {
    const zoom = map.getZoom();
    const names = phoneNames ? stateNamesAt(states, zoom, hiddenNames.states) : [];
    const small = phoneNames ? smallStateNamesAt(states, zoom, hiddenNames.states) : [];
    drawnStates = names;
    if (!sameNames(small, smallStates)) {
      smallStates = small;
      whenStyled(() => {
        setLayoutProperty(
          BASEMAP_IDS.usStateLabel,
          'text-size',
          stateNameSizeExpression(smallStates),
        );
      });
    }
    filterStateNames();
  }

  /** Sets the bundled layer's filter to the names it draws now, when they have changed. */
  function filterStateNames(): void {
    const kept = bundledKept;
    const names = kept === null ? drawnStates : drawnStates.filter((name) => kept.has(name));
    if (sameNames(names, filteredStates)) return;
    filteredStates = names;
    whenStyled(() => {
      setFilter(BASEMAP_IDS.usStateLabel, stateNameFilter(filteredStates));
    });
  }
  let stateNamesTimer: number | undefined;
  /** During a zoom, the state names follow every STATE_NAMES_REFRESH_MS at most. */
  const onZoom = (): void => {
    if (stateNamesTimer !== undefined) return;
    stateNamesTimer = window.setTimeout(() => {
      stateNamesTimer = undefined;
      refreshStateNames();
    }, STATE_NAMES_REFRESH_MS);
  };
  /** And exactly once it ends. */
  const onZoomEnd = (): void => {
    window.clearTimeout(stateNamesTimer);
    stateNamesTimer = undefined;
    refreshStateNames();
  };

  /** Runs a change to the style's layers now, or once the style is in if it is still loading. */
  function whenStyled(apply: () => void): void {
    try {
      apply();
    } catch {
      map.once('style.load', apply);
    }
  }

  /**
   * The states in view, named on a phone as the map comes to rest closer in
   * (state-areas.ts): their shapes load the first time a view needs them.
   */
  let stateAreas: Promise<readonly StateArea[] | null> | null = null;
  const loadStateAreas = (): Promise<readonly StateArea[] | null> => {
    stateAreas ??=
      stateAreasUrl === undefined
        ? Promise.resolve(null)
        : fetch(stateAreasUrl)
            .then(async (response) => (response.ok ? ((await response.json()) as unknown) : null))
            .then((data) => (data === null ? null : parseStateAreas(data)))
            .catch(() => null);
    return stateAreas;
  };
  // Every state's name, the ones too small to name before the handover too: closer in, they fit.
  const stateByName = new Map(stateNamesOf(usNames).map((state) => [state.name, state]));
  /** A state's name as set at a size: its lines' widest and their height, in CSS pixels. */
  const stateNameBox = (label: string, fontSize: number): { width: number; height: number } => {
    const lines = label.toUpperCase().split('\n');
    const width = Math.max(
      ...lines.map(
        (line) =>
          measure(line, fontSize) + Math.max(0, line.length - 1) * STATE_NAME_TRACKING * fontSize,
      ),
    );
    return { width, height: lines.length * fontSize * STATE_NAME_LEADING };
  };
  /** The place names on the screen now, as boxes, near enough: what a state's name moves off. */
  const placeNameBoxes = (zoom: number): ScreenRect[] => {
    const layers = [
      ...CITY_NAME_BANDS.map((_band, band) => cityNameLayerId(band)),
      BASEMAP_IDS.ofmCityLabel,
      BASEMAP_IDS.ofmTownLabel,
      BASEMAP_IDS.ofmVillageLabel,
    ].filter((id) => map.getLayer(id) !== undefined);
    const fontSize = zoom < OPENFREEMAP_MIN_ZOOM ? cityNameSize(zoom) : 14;
    return map.queryRenderedFeatures({ layers }).flatMap((feature) => {
      const geometry = feature.geometry as unknown as { type?: unknown; coordinates?: unknown };
      if (geometry.type !== 'Point' || !Array.isArray(geometry.coordinates)) return [];
      const [lon, lat] = geometry.coordinates as unknown[];
      if (typeof lon !== 'number' || typeof lat !== 'number') return [];
      const point = map.project([lon, lat]);
      const name = (feature.properties as { name?: unknown }).name;
      const half = measure(typeof name === 'string' ? name : '', fontSize) / 2 + 4;
      return [
        { x0: point.x - half, y0: point.y - fontSize, x1: point.x + half, y1: point.y + fontSize },
      ];
    });
  };
  /** Which refresh is the latest: an earlier one still loading the shapes gives way. */
  let stateAreaRound = 0;
  /**
   * The states the states-in-view layer names now: the ones it was last
   * given, and until those are drawn, the ones before them too.
   */
  let areaNames: ReadonlySet<string> = new Set();
  /** Which of its names that layer was last given: a later set replaces an earlier one. */
  let areaData = 0;
  /** Resolves once a source's tiles are all in and a frame has drawn them. */
  const whenSourceDrawn = (id: string): Promise<void> =>
    new Promise((resolve) => {
      const check = (): void => {
        if (!sourceIn(id)) return;
        map.off('render', check);
        resolve();
      };
      map.on('render', check);
      map.triggerRepaint();
    });
  /**
   * Gives the states-in-view layer its names. Resolves once they are drawn:
   * true, or false when a later set came first.
   */
  async function setStateAreas(
    source: GeoJSONSource,
    features: StateAreaFeature[],
  ): Promise<boolean> {
    const data = ++areaData;
    const names = new Set(features.map((feature) => feature.properties.name));
    areaNames = new Set([...areaNames, ...names]);
    await source.setData({ type: 'FeatureCollection', features });
    await whenSourceDrawn(BASEMAP_IDS.usStateAreaSource);
    if (data !== areaData) return false;
    areaNames = names;
    return true;
  }
  /**
   * The states-in-view layer names nothing, and once that is drawn, the
   * bundled layer names every state that fits.
   */
  function clearStateAreas(source: GeoJSONSource | undefined): void {
    const unlock = (): void => {
      bundledKept = null;
      filterStateNames();
    };
    if (areaNames.size === 0 || source === undefined) {
      unlock();
      return;
    }
    void setStateAreas(source, []).then((current) => {
      if (current) unlock();
    });
  }
  /**
   * Names the states in view, where the map has come to rest: on a phone,
   * from the bundled names' first zoom up to STATE_AREAS_UNTIL, each state
   * whose bundled name is set whole in the frame there, the rest where they
   * have room. The states-in-view layer draws them all, the bundled layer
   * none: no state is named twice, whichever way its names come and go.
   */
  function refreshStateAreas(): void {
    const round = ++stateAreaRound;
    const zoom = map.getZoom();
    const source = map.getSource<GeoJSONSource>(BASEMAP_IDS.usStateAreaSource);
    if (!phoneNames || zoom < STATE_NAME_SIZE.fromZoom || !(zoom < STATE_AREAS_UNTIL)) {
      clearStateAreas(source);
      return;
    }
    void loadStateAreas().then((areas) => {
      if (areas === null || source === undefined) return;
      if (round !== stateAreaRound || map.isMoving()) return;
      const { width, height } = size();
      const padding = fitPadding();
      const frame = {
        x0: padding.left,
        y0: padding.top,
        x1: width - padding.right,
        y1: height - padding.bottom,
      };
      const at = map.getZoom();
      const center = map.getCenter();
      // The bundled names as the map sets them now: the ones whole in the frame stay there.
      const set: SetName[] = drawnStates.flatMap((name) => {
        const state = stateByName.get(name);
        if (state === undefined) return [];
        const point = map.project([state.lon, state.lat]);
        return [
          {
            name,
            x: point.x,
            y: point.y,
            ...stateNameBox(state.label, stateNameSizeFor(state, at)),
          },
        ];
      });
      // Where the map would not draw a name: under the page's controls or at the screen's edges.
      const clear = CONTROL_CLEARANCE + STATE_NAME_PADDING + LABEL_SLACK;
      const blocked = clearance.boxes().map((box) => ({
        x0: box.x0 - clear,
        y0: box.y0 - clear,
        x1: box.x1 + clear,
        y1: box.y1 + clear,
      }));
      const kept = keptNames(set, frame, 2 * STATE_NAME_PADDING + LABEL_SLACK, blocked);
      const small = new Set(smallStates);
      const fontSize = stateNameSize(at);
      const spots = stateSpots(areas, {
        view: { lat: center.lat, lon: center.lng, zoom: at },
        screen: { width, height },
        frame,
        nameSize: (name) => {
          const state = stateByName.get(name);
          return state === undefined ? null : stateNameBox(state.label, fontSize);
        },
        avoid: [...placeNameBoxes(at), ...kept.map(nameBox)],
        skip: new Set(kept.map((name) => name.name)),
        blocked,
      });
      const feature = (
        name: string,
        lon: number,
        lat: number,
        scale: number,
      ): StateAreaFeature => ({
        type: 'Feature',
        properties: { name, label: stateByName.get(name)?.label ?? name, scale },
        geometry: { type: 'Point', coordinates: [lon, lat] },
      });
      const features = [
        // A bundled name kept is set just as the bundled layer sets it.
        ...kept.flatMap(({ name }) => {
          const state = stateByName.get(name);
          if (state === undefined) return [];
          return [feature(name, state.lon, state.lat, small.has(name) ? STATE_NAME_SMALL : 1)];
        }),
        ...spots.map((spot) => {
          const { lng, lat } = map.unproject([spot.x, spot.y]);
          return feature(spot.name, lng, lat, 1);
        }),
      ];
      // First the bundled layer lets go of every name this one is to set elsewhere, or still
      // sets somewhere: it keeps only the ones this one is to set at the same spot and size.
      // Once that is drawn, this layer takes its names; once those are drawn, the bundled
      // layer lets go of the rest. At no step is a state named in two places.
      const before = areaNames;
      bundledKept = new Set(kept.map((name) => name.name).filter((name) => !before.has(name)));
      filterStateNames();
      void whenSourceDrawn(BASEMAP_IDS.usCitySource).then(async () => {
        if (round !== stateAreaRound) return;
        const current = await setStateAreas(source, features);
        if (!current || round !== stateAreaRound) return;
        bundledKept = new Set();
        filterStateNames();
      });
    });
  }

  const onUserMove = (): void => {
    // Someone is moving the map before it has every layer: it takes them all on now.
    needAllLayers();
    held.release(false);
    moved = true;
    handMoves++;
    window.clearTimeout(deadline);
    releaseTileRequests();
    stopped = false;
    national = false;
    hideNames(NONE_HIDDEN);
    // Someone is moving the map: show it now, finished or not.
    goLive();
  };
  const onMoveStart = (event: MapMovementEvent): void => {
    if (event.originalEvent !== undefined) onUserMove();
  };
  function showHome(options: { animate?: boolean } = {}): void {
    cancelFlight();
    national = true;
    hideNames(cutAtHome());
    const animate = options.animate ?? false;
    if (homeIsNational()) {
      map.fitBounds(bounds, { padding: fitPadding(), animate });
      return;
    }
    const { lat, lon, zoom } = limits.home;
    needAllLayers();
    if (animate) map.easeTo({ center: [lon, lat], zoom });
    else map.jumpTo({ center: [lon, lat], zoom });
  }
  function showNear(place: Place): boolean {
    const next = viewLimits(size(), fitPadding(), place);
    if (next.home === next.fit) return false;
    near = place;
    limits = next;
    map.setTransformConstrain(constrainer(limits));
    flyTo(limits.home);
    // On its way home: the address names no view, as at the start.
    national = true;
    return true;
  }
  function goTo(target: MapView | null): void {
    // Where the map goes now says where they are going, not what their search shows first.
    window.clearTimeout(resultTimer);
    if (target === null) {
      showHome();
      return;
    }
    cancelFlight();
    national = false;
    hideNames(NONE_HIDDEN);
    const allowed = constrainView(limits, target);
    needAllLayers();
    map.jumpTo({ center: [allowed.lon, allowed.lat], zoom: allowed.zoom });
  }
  /**
   * Whether a source's tiles for the view are all in (or failed), as of the
   * last frame drawn; not while the map has no such source yet (its layers
   * come in turns), which MapLibre would report as an error.
   */
  const sourceIn = (id: string): boolean => {
    if (styleOf(map)?.tileManagers[id] === undefined) return false;
    try {
      return map.isSourceLoaded(id);
    } catch {
      return true;
    }
  };
  /**
   * Whether the street tiles in view have all come in or failed, and some
   * failed: nothing more is coming for now (heal.ts asks for them again).
   */
  const streetTilesFailed = (): boolean =>
    failedTiles(map, BASEMAP_IDS.openFreeMapSource).length > 0 &&
    sourceIn(BASEMAP_IDS.openFreeMapSource);
  /**
   * The zoom of the coarsest street tiles the map draws across the screen, or
   * null while some part of it has none (flight.ts streetTileZoom).
   */
  const coarsestStreetTiles = (): number | null => {
    const tiles = map.style.tileManagers[BASEMAP_IDS.openFreeMapSource];
    if (tiles === undefined) return null;
    const loaded: LoadedTile[] = tiles.getIds().flatMap((id) => {
      const tile = tiles.getTileByID(id);
      if (tile?.hasData() !== true) return [];
      const { canonical, overscaledZ } = tile.tileID;
      return [{ z: canonical.z, x: canonical.x, y: canonical.y, zoom: overscaledZ }];
    });
    if (loaded.length === 0) return null;
    const { width, height } = size();
    const points = coverPoints(width, height).map((point) => {
      const { lng, lat } = map.unproject(point);
      return { x: mercatorXFromLng(lng), y: mercatorYFromLat(lat) };
    });
    return streetTileZoom(points, loaded);
  };
  /** The closest the camera may be now, with the street tiles on screen. */
  const ceiling = (): number => flightCeiling(coarsestStreetTiles(), FLIGHT_STOP_ZOOM);
  /** Checks the wait in progress (holdUntil) again at once, if any: for a flight told to hurry. */
  let checkHold: (() => void) | null = null;
  /**
   * Resolves true once `ready` holds, checked as tiles come in and frames are
   * drawn, or false after `ms`.
   */
  const holdUntil = (ready: () => boolean, ms: number = FLIGHT_HOLD_MS): Promise<boolean> =>
    new Promise((resolve) => {
      if (ready()) {
        resolve(true);
        return;
      }
      const done = (result: boolean): void => {
        window.clearTimeout(timer);
        map.off('sourcedata', check);
        map.off('error', check);
        map.off('render', check);
        map.off('idle', check);
        if (checkHold === check) checkHold = null;
        resolve(result);
      };
      /** Checking, once at a time: what it asks of the map may fire an event it listens for. */
      let checking = false;
      const check = (): void => {
        if (checking) return;
        checking = true;
        try {
          if (ready()) done(true);
        } finally {
          checking = false;
        }
      };
      const timer = window.setTimeout(
        () => {
          done(false);
        },
        Math.max(0, ms),
      );
      map.on('sourcedata', check);
      // A tile that fails is no data event, and draws no frame.
      map.on('error', check);
      map.on('render', check);
      map.on('idle', check);
      checkHold = check;
    });
  /** Whether MapLibre jumps instead of flying: the viewer prefers reduced motion. */
  const reducedMotion = (): boolean =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  /**
   * Whether the map draws the view it is at: the bundled lines and names
   * below the handover, street tiles from it.
   */
  const viewDrawn = (): boolean =>
    map.getZoom() < BUNDLED_LINES_UNTIL
      ? sourceIn(BASEMAP_IDS.usSource) && sourceIn(BASEMAP_IDS.usCitySource)
      : coarsestStreetTiles() !== null;
  // A map opening off the national view shows as soon as it has every layer and has drawn its
  // view, all of it on screen: every other tile (a school's, a name's) can come after.
  if (!opensNational) {
    const revealWhenDrawn = (): void => {
      if (live || pendingLayers.length > 0 || !viewDrawn()) return;
      map.off('render', revealWhenDrawn);
      goLiveWhenDrawn();
    };
    map.on('render', revealWhenDrawn);
  }
  /**
   * Cuts to `view`: the frame the map shows now stays on screen, still, until
   * the map has drawn `view` (or FLIGHT_HOLD_MS), and fades out over it. For
   * a flight out of the streets to a place far off, whose way there crosses
   * streets the map has none of. `then` runs as it fades.
   */
  function cutTo(view: MapView, current: () => boolean, then: () => void): void {
    map.once('render', () => {
      if (!current()) {
        then();
        return;
      }
      // The frame just drawn, before it is on screen: after, the canvas is empty.
      held.hold(map.getCanvas());
      map.jumpTo({ center: [view.lon, view.lat], zoom: view.zoom });
      let drawn = false;
      map.once('render', () => {
        drawn = true;
      });
      void holdUntil(() => drawn && viewDrawn()).then(() => {
        held.release(!reducedMotion());
        then();
      });
    });
    map.triggerRepaint();
  }
  /**
   * Whether the view a flight goes to is on the screen now, give or take
   * ON_SCREEN_MARGIN: the street tiles the map has cover it, and it glides
   * there (a school to the next one, a street view closer in).
   */
  const onScreen = (target: MapView): boolean => {
    const { width, height } = size();
    // The view it goes to, as it would lie on the screen now.
    const scale = 2 ** (map.getZoom() - target.zoom);
    const there = map.project([target.lon, target.lat]);
    const halfWidth = (width / 2) * scale;
    const halfHeight = (height / 2) * scale;
    const marginX = width * ON_SCREEN_MARGIN;
    const marginY = height * ON_SCREEN_MARGIN;
    return (
      there.x - halfWidth >= -marginX &&
      there.x + halfWidth <= width + marginX &&
      there.y - halfHeight >= -marginY &&
      there.y + halfHeight <= height + marginY
    );
  };
  /** Whether `view`, on the screen, would show the place in the middle of the screen now. */
  const around = (view: MapView): boolean => {
    const { width, height } = size();
    const here = map.getCenter();
    const world = 512 * 2 ** view.zoom;
    const dx = (mercatorXFromLng(here.lng) - mercatorXFromLng(view.lon)) * world;
    const dy = (mercatorYFromLat(here.lat) - mercatorYFromLat(view.lat)) * world;
    return Math.abs(dx) <= width / 2 && Math.abs(dy) <= height / 2;
  };
  /** How a flight on its way goes on: told to hurry past its deadline, it waits for no tile. */
  interface FlightPace {
    hurried: boolean;
  }
  /** Each leg of a flight (a camera move it starts) is numbered: moveend says which one ended. */
  let legs = 0;
  /**
   * Starts a camera move as a leg of a flight: `then` runs once it ends,
   * however it ends (arrived, stopped by the flight, or cut short by another
   * move). MapLibre's moveend carries the data the move was started with, so
   * no other move's end is taken for this one's. A glide taking `glideMs`
   * asks for no street or school tiles on its way: the zooms it passes, it
   * passes on tiles already drawn (flight.ts), and the tiles it stops at are
   * asked for as it stops (or once its time is well past, whatever became of
   * it).
   */
  function leg(
    move: (data: { snowlightLeg: number }) => void,
    then: () => void,
    glideMs?: number,
  ): void {
    const data = { snowlightLeg: ++legs };
    const ended = (event: MapMovementEvent & { snowlightLeg?: number }): void => {
      if (event.snowlightLeg !== data.snowlightLeg) return;
      map.off('moveend', ended);
      if (glideMs !== undefined) releaseTileRequests();
      then();
    };
    map.on('moveend', ended);
    if (glideMs !== undefined) holdTileRequests(glideMs + GLIDE_HOLD_SLACK_MS);
    move(data);
  }
  /** Whether the map is at `view`, as a flight there leaves it. */
  const at = (view: MapView): boolean => {
    const center = map.getCenter();
    return (
      Math.abs(map.getZoom() - view.zoom) < 1e-3 &&
      Math.abs(center.lat - view.lat) < 1e-6 &&
      Math.abs(center.lng - view.lon) < 1e-6
    );
  };
  /**
   * The last leg of a flight into streets, from its stop (or from streets on
   * screen) straight in to `target`: a glide that goes no closer than the
   * street tiles on screen allow (flight.ts), waits there for closer ones,
   * and glides on; once the tiles fail, or the waits add up to
   * FLIGHT_HOLD_MS, it glides straight in. `then` runs once it arrives, or
   * once someone moves the map or another flight takes over. A glide cut
   * short by anything else goes on from where it is.
   */
  function zoomIn(
    target: MapView,
    current: () => boolean,
    then: () => void,
    pace: FlightPace,
  ): void {
    /** Paced until the tiles fail or the waits run out: then the flight goes on without them. */
    let paced = true;
    /** Milliseconds waited for tiles so far, all the waits together. */
    let waited = 0;
    const glide = (): void => {
      if (!current()) {
        then();
        return;
      }
      const since = performance.now();
      const verdict = (): HoldVerdict => {
        if (!paced || pace.hurried) return 'go-on';
        try {
          return holdVerdict({
            ceiling: ceiling(),
            zoom: map.getZoom(),
            failed: streetTilesFailed(),
            waited: waited + performance.now() - since,
          });
        } catch {
          // The map could not say what it has drawn: no pacing, rather than no end.
          return 'go-on';
        }
      };
      void holdUntil(() => verdict() !== 'wait', FLIGHT_HOLD_MS - waited).then(() => {
        waited += performance.now() - since;
        if (!current()) {
          then();
          return;
        }
        if (verdict() !== 'glide') paced = false;
        if (reducedMotion()) {
          // MapLibre jumps: straight there.
          stopped = false;
          leg(
            (data) => map.jumpTo({ center: [target.lon, target.lat], zoom: target.zoom }, data),
            then,
          );
          return;
        }
        const from = map.getZoom();
        const duration = Math.max(1, target.zoom - from) * FLIGHT_MS_PER_ZOOM;
        let shown = 0;
        let arrived = false;
        let over = false;
        let holding = false;
        leg(
          (data) =>
            map.easeTo(
              {
                center: [target.lon, target.lat],
                zoom: target.zoom,
                duration,
                essential: true,
                easing: (t) => {
                  let limit = 1;
                  if (paced && !pace.hurried && current()) {
                    try {
                      limit = progressAt(from, target.zoom, ceiling());
                    } catch {
                      paced = false;
                    }
                  }
                  shown = pacedProgress(shown, flightEasing(t), limit);
                  if (shown >= 1) {
                    arrived = true;
                    // Arrived: the address takes this view as the flight ends.
                    stopped = false;
                  } else if ((shown >= limit || t >= 1) && !holding) {
                    // As far as the tiles allow: end the glide once this frame is drawn, and wait.
                    holding = true;
                    queueMicrotask(() => {
                      if (!over) map.stop();
                    });
                  }
                  return shown;
                },
              },
              data,
            ),
          () => {
            over = true;
            // Held short of the tiles, or cut short by something other than a person or another
            // flight: on in, from here.
            if (current() && !arrived) glide();
            else then();
          },
          duration,
        );
      });
    };
    glide();
  }
  function flyTo(target: MapView): void {
    // Where the map goes now says where they are going, not what their search shows first.
    window.clearTimeout(resultTimer);
    national = false;
    hideNames(NONE_HIDDEN);
    const allowed = constrainView(limits, target);
    needAllLayers();
    const zoom = map.getZoom();
    const intoStreets = allowed.zoom > FLIGHT_STOP_ZOOM + 0.5;
    /**
     * How it goes: from the streets, a glide to a view on screen, or a cut
     * to one that is not, whose way there crosses streets the map has none
     * of (to FLIGHT_LEAD levels out from it, or to it, short of the streets);
     * from the bundled lines, a flight, into the streets by way of a stop.
     */
    const from: 'glide' | 'cut' | 'fly' =
      zoom < BUNDLED_LINES_UNTIL ? 'fly' : onScreen(allowed) ? 'glide' : 'cut';
    // A cut out to a view around where the map is (a school's town) goes straight there; one
    // elsewhere arrives from FLIGHT_LEAD levels out, and glides in.
    const stop: MapView | null =
      from === 'glide' || !intoStreets || (from === 'cut' && around(allowed))
        ? null
        : {
            ...allowed,
            zoom:
              from === 'cut'
                ? Math.max(FLIGHT_STOP_ZOOM, allowed.zoom - FLIGHT_LEAD)
                : FLIGHT_STOP_ZOOM,
          };
    // The tiles it stops at and ends on, asked for before it gets there: those wholly inside the
    // US at once, the rest once the mask is in (no such tile draws before it, and on a slow link
    // they would only slow it down). A flight with any of the rest asks for the mask as it goes.
    const paceFrom = Math.floor(stop?.zoom ?? zoom);
    const slow = slowLink();
    const limit = flightTileLimit();
    const ahead = [
      ...(stop === null ? [] : flightTiles(stop, size(), paceFrom).slice(0, limit)),
      ...flightTiles(allowed, size(), paceFrom).slice(0, limit),
    ];
    if (needMask(ahead)) maskFeed.start();
    // The ones it ends on go at once, beside the rest in their order, so they are never last in
    // line; on a slow link, in their turn, the first the flight draws coming first.
    const top = Math.min(Math.floor(allowed.zoom), OPENFREEMAP_MAX_ZOOM);
    const queues = slow
      ? [ahead]
      : [ahead.filter(([z]) => z === top), ahead.filter(([z]) => z !== top)];
    for (const tiles of queues) {
      const whole = tiles.filter(([z, x, y]) => insideUs(z, x, y));
      const cut = tiles.filter(([z, x, y]) => !insideUs(z, x, y));
      void prefetchOpenFreeMapTiles(whole).then(async () => {
        // Those the mask says are wholly outside the US are never asked for.
        if (cut.length > 0) await prefetchOpenFreeMapTiles(await maskFeed.inUs(cut));
      });
    }
    const flight = ++flights;
    const hand = handMoves;
    const current = (): boolean => flight === flights && hand === handMoves;
    const pace: FlightPace = { hurried: false };
    // An earlier flight stops here, before this one listens for its own end.
    map.stop();
    held.release(false);
    stopped = false;
    map.cancelPendingTileRequestsWhileZooming = false;
    const land = (): void => {
      if (flight !== flights) return;
      window.clearTimeout(deadline);
      releaseTileRequests();
      stopped = false;
      map.cancelPendingTileRequestsWhileZooming = true;
    };
    // Past its deadline a flight waits for nothing; past its last call, it is put where it goes.
    window.clearTimeout(deadline);
    const watch = (ms: number, last: boolean): void => {
      deadline = window.setTimeout(() => {
        if (!current()) return;
        // Time the page is hidden, and the camera still, is not the flight's.
        if (document.visibilityState === 'hidden') {
          watch(1000, last);
          return;
        }
        if (!last) {
          pace.hurried = true;
          checkHold?.();
          watch(FLIGHT_LAST_CALL_MS - FLIGHT_DEADLINE_MS, true);
          return;
        }
        cancelFlight();
        map.jumpTo({ center: [allowed.lon, allowed.lat], zoom: allowed.zoom });
      }, ms);
    };
    watch(FLIGHT_DEADLINE_MS, false);
    /** On in from where the leg before left it: straight in to the destination, paced by tiles. */
    const goIn = (): void => {
      if (!current() || at(allowed)) {
        land();
        return;
      }
      zoomIn(allowed, current, land, pace);
    };
    // Short of where it is going, the address keeps where it was: it takes the view it arrives at.
    stopped = stop !== null || from === 'glide';
    if (from === 'glide') {
      zoomIn(allowed, current, land, pace);
      return;
    }
    if (from === 'cut') {
      cutTo(stop ?? allowed, current, goIn);
      return;
    }
    const view = stop ?? allowed;
    // Not essential: MapLibre jumps instead when the viewer prefers reduced motion.
    leg(
      (data) =>
        map.flyTo({ center: [view.lon, view.lat], zoom: view.zoom, essential: false }, data),
      goIn,
    );
  }
  function fitBounds(
    box: readonly [number, number, number, number],
    options: { maxZoom?: number } = {},
  ): void {
    const camera = map.cameraForBounds(
      [
        [box[0], box[1]],
        [box[2], box[3]],
      ],
      { padding: fitPadding(), maxZoom: options.maxZoom ?? MAX_ZOOM },
    );
    if (camera?.center === undefined || camera.zoom === undefined) return;
    const center = maplibre.LngLat.convert(camera.center);
    flyTo({ lat: center.lat, lon: center.lng, zoom: camera.zoom });
  }
  /**
   * New limits for the window's new size, applied before anything is drawn at
   * it: the view moves to the nearest allowed one, and the home view is
   * fitted afresh (a phone turned on its side goes to the national view).
   */
  const onResize = (): void => {
    limits = viewLimits(size(), fitPadding(), near);
    map.setTransformConstrain(constrainer(limits));
    map.setMinZoom(limits.minZoom);
    const wanted = phoneNamesWanted();
    if (wanted !== phoneNames) {
      phoneNames = wanted;
      whenStyled(() => {
        const padding = phoneNames ? CITY_NAME_PHONE_PADDING : CITY_NAME_PADDING;
        CITY_NAME_BANDS.forEach((_band, band) => {
          setLayoutProperty(cityNameLayerId(band), 'text-padding', padding);
        });
        const visibility = phoneNames ? 'visible' : 'none';
        setLayoutProperty(BASEMAP_IDS.usStateLabel, 'visibility', visibility);
        setLayoutProperty(BASEMAP_IDS.usStateAreaLabel, 'visibility', visibility);
      });
      refreshStateNames();
      refreshStateAreas();
    }
    if (national) showHome();
  };
  map.on('movestart', onMoveStart);
  map.on('moveend', refreshStateAreas);
  map.once('idle', refreshStateAreas);
  map.on('zoom', onZoom);
  map.on('zoomend', onZoomEnd);
  // A wheel or trackpad zoom often starts without an event on movestart; its wheel event says who moved it.
  map.on('wheel', onUserMove);
  map.on('resize', onResize);
  // Someone pressing on a school is on their way to it: what its streets need comes meanwhile.
  const schoolMarks = [BASEMAP_IDS.schoolDots, BASEMAP_IDS.schoolLight, BASEMAP_IDS.schoolNames];
  const onSchoolPress = (event: MapMouseEvent | MapTouchEvent): void => {
    streetsAhead({ lat: event.lngLat.lat, lon: event.lngLat.lng });
  };
  map.on('mousedown', schoolMarks, onSchoolPress);
  map.on('touchstart', schoolMarks, onSchoolPress);

  // Street and school tiles fail on a bad network, and are asked for again (heal.ts): say so once
  // for each, quietly.
  const warned = new Set<string>();
  const tileNames: Readonly<Record<string, string>> = {
    [BASEMAP_IDS.openFreeMapSource]: 'street tiles',
    [BASEMAP_IDS.schoolsSource]: 'school tiles',
  };
  map.on('error', (event) => {
    const sourceId = (event as { sourceId?: unknown }).sourceId;
    const tiles = typeof sourceId === 'string' ? tileNames[sourceId] : undefined;
    if (typeof sourceId === 'string' && tiles !== undefined) {
      if (!warned.has(sourceId)) {
        console.warn(`Snowlight: ${tiles} unavailable for now`, event.error.message);
      }
      warned.add(sourceId);
      return;
    }
    console.error(event.error);
  });

  // The style goes on in a task of its own: MapLibre sets part of it up as it takes it.
  await yieldToMain();
  map.setStyle(staged.style);

  return {
    map,
    ready,
    get moved() {
      return moved;
    },
    get national() {
      return national;
    },
    get flightStopped() {
      return stopped;
    },
    get view() {
      const center = map.getCenter();
      return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
    },
    get limits() {
      return limits;
    },
    controlsChanged() {
      map.triggerRepaint();
    },
    selectSchool(id) {
      // A build without the school tiles has no ring to draw.
      if (staged.order.includes(BASEMAP_IDS.schoolSelected)) {
        setFilter(BASEMAP_IDS.schoolSelected, selectedSchoolFilter(id));
      }
    },
    showHome,
    showNear,
    goTo,
    flyTo,
    fitBounds,
    prepareStreets,
    destroy() {
      // A flight on its way goes no further.
      cancelFlight();
      window.clearTimeout(revealTimer);
      window.clearTimeout(stateNamesTimer);
      window.clearTimeout(resultTimer);
      stopHealing();
      releaseTileRequests();
      maskFeed.destroy();
      clearance.destroy();
      stopWarming();
      if (window.snowlightMap === map) delete window.snowlightMap;
      map.remove();
      container.classList.remove(LIVE_CLASS);
    },
  };
}

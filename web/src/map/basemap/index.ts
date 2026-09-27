import './maplibre.css';

import type { Map as MapLibreMap, MapMovementEvent, TransformConstrainFunction } from 'maplibre-gl';
import { DATA_FILES } from 'virtual:snowlight/data-files';

import { mapLocale } from '../../copy';
import { DATA_PATHS, createDataFiles, dataRootFor } from '../../data/files';
import { collapsedAttribution } from './attribution';
import { cityNamesOf, namesCutByEdges, stateNamesCutByEdges, textMeasure } from './home-names';
import { addMapFonts } from './fonts';
import type { MapLibre } from './maplibre';
import { OPENFREEMAP_ATTRIBUTION, prefetchOpenFreeMapTiles } from './openfreemap';
import { MAX_ZOOM } from './bounds';
import type { MapView } from './bounds';
import { WHOLE_COUNTRY, constrainView, viewLimits } from './limits';
import type { HomeFit, Insets, Size, ViewLimits } from './limits';
import { flightTiles } from './prefetch';
import { afterNextFrame, LIVE_CLASS, markStep, whenGpuIdle } from './reveal';
import { SCHOOL_SPACE_IMAGE, schoolSpaceImage } from './schools';
import { namedStates, stateNamesAt, stateNamesOf } from './state-names';
import {
  BASEMAP_IDS,
  CITY_NAME_BANDS,
  CITY_NAME_PADDING,
  CITY_NAME_PHONE_PADDING,
  buildBasemapStyle,
  cityNameFilter,
  cityNameLayerId,
  stateNameFilter,
} from './style';
import type { BasemapLook, UsLinesData } from './style';
import { US_BOUNDS } from './us-geo';

export { BASEMAP_IDS } from './style';
export { US_BOUNDS } from './us-geo';
export type { MapView } from './bounds';
export type { ViewLimits } from './limits';

export interface BasemapOptions {
  /** Element the map fills. */
  container: HTMLElement;
  /**
   * Element whose box the continental US is fitted into at the national view,
   * and which says how the home view fits it (homeFit). The inline still in
   * index.html is laid out on the same box by the same rules, which is what
   * makes the handover invisible.
   */
  frame: HTMLElement;
  /**
   * A view to open at instead of the home view, such as one from a link.
   * The map opens at the nearest view its limits allow.
   */
  view?: MapView | null;
}

/** What load.ts fetched in parallel before the map is created. */
export interface BasemapResources {
  /** The MapLibre module. */
  maplibre: MapLibre;
  /** URL MapLibre starts its workers from (maplibre-worker.ts). */
  workerUrl: string;
  /** The bundled continental US lines, already fetched and parsed. */
  usLines: UsLinesData;
  /** The school tiles' archive this build ships, as an absolute URL, or null. */
  schools: string | null;
}

export interface Basemap {
  readonly map: MapLibreMap;
  /**
   * Resolves once the canvas is on screen showing the bundled US lines: after
   * the first complete frame, or as soon as someone moves the map. A view
   * from a link is shown by LINK_REVEAL_MS after the map is created.
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
  /** How far the map zooms out and pans on this screen; they follow the window's size. */
  readonly limits: ViewLimits;
  /** Goes to the home view, as at the start: the country fitted into the frame, or filling it. */
  showHome(options?: { animate?: boolean }): void;
  /** Moves to the nearest view the limits allow, or to the home view with null. */
  goTo(view: MapView | null): void;
  /** Glides to the nearest view the limits allow; jumps when reduced motion is preferred. */
  flyTo(view: MapView): void;
  /** Glides to show [west, south, east, north] inside the frame, no closer than `maxZoom`. */
  fitBounds(
    bounds: readonly [number, number, number, number],
    options?: { maxZoom?: number },
  ): void;
  destroy(): void;
}

/** MapLibre's size for a container that has none yet. */
const FALLBACK_SIZE: Size = { width: 400, height: 300 };

const NO_PADDING: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

/** Workers parse the bundled lines and, from zoom 7, vector tiles; two is plenty. */
const WORKERS = 2;

/**
 * A view opened from a link is not the home view the inline still shows,
 * so the map is shown by this long after it is created, whether or not every
 * tile of the view is in: a slow tile or a busy GPU never leaves the still of
 * the whole country standing over a street.
 */
export const LINK_REVEAL_MS = 2500;

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
  maplibre.setWorkerCount(WORKERS);
  configured = maplibre;
}

/**
 * Starts MapLibre's workers ahead of the map, so they load MapLibre's shared
 * module while the map is being created rather than after.
 */
export function startWorkers(maplibre: MapLibre, workerUrl: string): void {
  configure(maplibre, workerUrl);
  maplibre.prewarm();
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

/**
 * How the home view fits the country into `frame`, from the custom
 * properties index.html sets on it where the still covers the frame (a phone
 * held upright): --home-fit is "cover" there, and --home-focus places the
 * country across, 0 to 1. Anywhere else the home view is the national view.
 */
export function homeFit(frame: Element): HomeFit {
  const style = getComputedStyle(frame);
  if (style.getPropertyValue('--home-fit').trim() !== 'cover') return WHOLE_COUNTRY;
  const focus = Number.parseFloat(style.getPropertyValue('--home-focus'));
  return { cover: true, focus: Number.isFinite(focus) ? focus : WHOLE_COUNTRY.focus };
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
 * Creates the WebGL basemap from what load.ts fetched. Construction is
 * synchronous; `ready` resolves once the bundled lines are on screen.
 */
export function createBasemap({
  container,
  frame,
  view = null,
  maplibre,
  workerUrl,
  usLines,
  schools,
}: BasemapOptions & BasemapResources): Basemap {
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
  let limits = viewLimits(size(), fitPadding(), homeFit(frame));
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
  const cities = cityNamesOf(usLines);
  const states = namedStates(stateNamesOf(usLines));
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

  const map = new maplibre.Map({
    container,
    style: buildBasemapStyle({
      usLines,
      schools,
      hiddenCityNames: hiddenNames.cities,
      stateNames: drawnStates,
      ...initialLook,
    }),
    locale: mapLocale,
    ...(start === null && homeIsNational()
      ? { bounds, fitBoundsOptions: { padding: fitPadding() } }
      : {
          center: [(start ?? limits.home).lon, (start ?? limits.home).lat] as [number, number],
          zoom: (start ?? limits.home).zoom,
        }),
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
  });
  markStep('map-created');
  // A dot's space is made here the first time the style needs it: the style names no sprite.
  map.setMissingStyleImageResolver((id) => {
    if (map.hasImage(id)) return;
    if (id === SCHOOL_SPACE_IMAGE) map.addImage(SCHOOL_SPACE_IMAGE, schoolSpaceImage());
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(
    collapsedAttribution(maplibre, { customAttribution: OPENFREEMAP_ATTRIBUTION }),
    'bottom-right',
  );
  // End-to-end tests read what the map drew; only a browser under automation gets the handle.
  if (navigator.webdriver) window.snowlightMap = map;

  let moved = false;
  let national = start === null;
  let live = false;
  let markReady: () => void = () => undefined;
  const ready = new Promise<void>((resolve) => {
    markReady = resolve;
  });
  const goLive = (): void => {
    if (live) return;
    live = true;
    container.classList.add(LIVE_CLASS);
    markStep('map-live');
    void afterNextFrame().then(markReady);
  };
  map.once('load', () => {
    markStep('map-load');
    const gl = map.getCanvas().getContext('webgl2');
    if (gl === null) goLive();
    else void whenGpuIdle(gl).then(goLive);
  });
  const revealTimer = start === null ? undefined : window.setTimeout(goLive, LINK_REVEAL_MS);

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
          map.setFilter(cityNameLayerId(band), cityNameFilter(band, hiddenNames.cities));
        });
      });
    }
    refreshStateNames();
  }

  /**
   * Keeps the state names' one layer to the states whose names fit at the
   * map's zoom, less those left out: it changes only when the zoom crosses
   * the zoom a state's name fits at.
   */
  function refreshStateNames(): void {
    const names = phoneNames ? stateNamesAt(states, map.getZoom(), hiddenNames.states) : [];
    if (sameNames(names, drawnStates)) return;
    drawnStates = names;
    whenStyled(() => {
      map.setFilter(BASEMAP_IDS.usStateLabel, stateNameFilter(drawnStates));
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

  const onUserMove = (): void => {
    moved = true;
    national = false;
    hideNames(NONE_HIDDEN);
    // Someone is moving the map: show it now, finished or not.
    goLive();
  };
  const onMoveStart = (event: MapMovementEvent): void => {
    if (event.originalEvent !== undefined) onUserMove();
  };
  function showHome(options: { animate?: boolean } = {}): void {
    national = true;
    hideNames(cutAtHome());
    const animate = options.animate ?? false;
    if (homeIsNational()) {
      map.fitBounds(bounds, { padding: fitPadding(), animate });
      return;
    }
    const { lat, lon, zoom } = limits.home;
    if (animate) map.easeTo({ center: [lon, lat], zoom });
    else map.jumpTo({ center: [lon, lat], zoom });
  }
  function goTo(target: MapView | null): void {
    if (target === null) {
      showHome();
      return;
    }
    national = false;
    hideNames(NONE_HIDDEN);
    const allowed = constrainView(limits, target);
    map.jumpTo({ center: [allowed.lon, allowed.lat], zoom: allowed.zoom });
  }
  /**
   * Keeps every tile a flight asks for loading until it arrives, instead of
   * dropping the ones the camera has zoomed past: each is drawn, scaled up,
   * until the closer ones are in, so the map shows streets all the way in.
   * Zooming by hand drops them again once the flight is over.
   */
  let flights = 0;
  const keepTilesWhileFlying = (): void => {
    if (!map.isMoving()) return;
    const flight = ++flights;
    map.cancelPendingTileRequestsWhileZooming = false;
    map.once('moveend', () => {
      if (flight === flights) map.cancelPendingTileRequestsWhileZooming = true;
    });
  };
  function flyTo(target: MapView): void {
    national = false;
    hideNames(NONE_HIDDEN);
    const allowed = constrainView(limits, target);
    // The tiles it ends on, and the ones it passes on the way, asked for before it starts.
    void prefetchOpenFreeMapTiles(flightTiles(allowed, size()));
    // Not essential: MapLibre jumps instead when the viewer prefers reduced motion.
    map.flyTo({ center: [allowed.lon, allowed.lat], zoom: allowed.zoom, essential: false });
    keepTilesWhileFlying();
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
    limits = viewLimits(size(), fitPadding(), homeFit(frame));
    map.setTransformConstrain(constrainer(limits));
    map.setMinZoom(limits.minZoom);
    const wanted = phoneNamesWanted();
    if (wanted !== phoneNames) {
      phoneNames = wanted;
      whenStyled(() => {
        const padding = phoneNames ? CITY_NAME_PHONE_PADDING : CITY_NAME_PADDING;
        CITY_NAME_BANDS.forEach((_band, band) => {
          map.setLayoutProperty(cityNameLayerId(band), 'text-padding', padding);
        });
        const visibility = phoneNames ? 'visible' : 'none';
        map.setLayoutProperty(BASEMAP_IDS.usStateLabel, 'visibility', visibility);
      });
      refreshStateNames();
    }
    if (national) showHome();
  };
  map.on('movestart', onMoveStart);
  map.on('zoom', onZoom);
  map.on('zoomend', onZoomEnd);
  // A wheel or trackpad zoom often starts without an event on movestart; its wheel event says who moved it.
  map.on('wheel', onUserMove);
  map.on('resize', onResize);

  // Tile errors from OpenFreeMap are expected when offline; say so once, quietly.
  let warnedTiles = false;
  map.on('error', (event) => {
    const sourceId = (event as { sourceId?: unknown }).sourceId;
    if (sourceId === BASEMAP_IDS.openFreeMapSource) {
      if (!warnedTiles) console.warn('Snowlight: street tiles unavailable', event.error.message);
      warnedTiles = true;
      return;
    }
    console.error(event.error);
  });

  return {
    map,
    ready,
    get moved() {
      return moved;
    },
    get national() {
      return national;
    },
    get view() {
      const center = map.getCenter();
      return { lat: center.lat, lon: center.lng, zoom: map.getZoom() };
    },
    get limits() {
      return limits;
    },
    showHome,
    goTo,
    flyTo,
    fitBounds,
    destroy() {
      window.clearTimeout(revealTimer);
      window.clearTimeout(stateNamesTimer);
      if (window.snowlightMap === map) delete window.snowlightMap;
      map.remove();
      container.classList.remove(LIVE_CLASS);
    },
  };
}

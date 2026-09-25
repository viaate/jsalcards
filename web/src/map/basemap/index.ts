import './maplibre.css';

import type { Map as MapLibreMap, MapMovementEvent, TransformConstrainFunction } from 'maplibre-gl';

import { mapLocale } from '../../copy';
import { collapsedAttribution } from './attribution';
import type { MapLibre } from './maplibre';
import { OPENFREEMAP_ATTRIBUTION, registerOpenFreeMap } from './openfreemap';
import { MAX_ZOOM } from './bounds';
import type { MapView } from './bounds';
import { constrainView, viewLimits } from './limits';
import type { Insets, Size, ViewLimits } from './limits';
import { afterNextFrame, LIVE_CLASS, markStep, whenGpuIdle } from './reveal';
import { BASEMAP_IDS, buildBasemapStyle } from './style';
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
   * Element whose box the continental US is fitted into at the initial view.
   * The inline still in index.html is drawn inside the same box, which is what
   * makes the handover invisible.
   */
  frame: HTMLElement;
  /**
   * A view to open at instead of the national view, such as one from a link.
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
}

export interface Basemap {
  readonly map: MapLibreMap;
  /**
   * Resolves once the canvas is on screen showing the bundled US lines: after
   * the first complete frame, or as soon as someone moves the map.
   */
  readonly ready: Promise<void>;
  /** True once someone has moved the map. */
  readonly moved: boolean;
  /**
   * True while the map shows the national view, which it keeps fitted to the
   * frame as the window resizes: from the start (unless it opened at a given
   * view) and after fitContinentalUs, until someone moves the map.
   */
  readonly national: boolean;
  /** Where the map is now. */
  readonly view: MapView;
  /** How far the map zooms out and pans on this screen; they follow the window's size. */
  readonly limits: ViewLimits;
  /** Fits the continental US into the frame, as at the initial view. */
  fitContinentalUs(options?: { animate?: boolean }): void;
  /** Moves to the nearest view the limits allow, or to the national view with null. */
  goTo(view: MapView | null): void;
  destroy(): void;
}

/** MapLibre's size for a container that has none yet. */
const FALLBACK_SIZE: Size = { width: 400, height: 300 };

const NO_PADDING: Insets = { top: 0, right: 0, bottom: 0, left: 0 };

/** Workers parse the bundled lines and, from zoom 7, vector tiles; two is plenty. */
const WORKERS = 2;

let configured: MapLibre | undefined;

/** MapLibre's global settings; they must be in place before the first map starts its workers. */
function configure(maplibre: MapLibre, workerUrl: string): void {
  if (configured === maplibre) return;
  maplibre.setWorkerUrl(workerUrl);
  maplibre.setWorkerCount(WORKERS);
  registerOpenFreeMap(maplibre);
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
 * Line colors and width come from the same CSS custom properties that draw the
 * inline still, so the two cannot drift apart.
 */
function look(): BasemapLook {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string): string => {
    const value = style.getPropertyValue(name).trim();
    return value === '' ? fallback : value;
  };
  const hairline = Number.parseFloat(token('--hairline', '1px'));
  return {
    hairline: Number.isFinite(hairline) && hairline > 0 ? hairline : 1,
    colors: {
      background: token('--bg', '#000'),
      outline: token('--line-outline', '#6b6b6b'),
      state: token('--line-state', '#2a2a2a'),
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
}: BasemapOptions & BasemapResources): Basemap {
  configure(maplibre, workerUrl);
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
  let limits = viewLimits(size(), fitPadding());
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

  const map = new maplibre.Map({
    container,
    style: buildBasemapStyle({ usLines, ...look() }),
    locale: mapLocale,
    ...(start === null
      ? { bounds, fitBoundsOptions: { padding: fitPadding() } }
      : { center: [start.lon, start.lat] as [number, number], zoom: start.zoom }),
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
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(
    collapsedAttribution(maplibre, { customAttribution: OPENFREEMAP_ATTRIBUTION }),
    'bottom-right',
  );

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

  const onUserMove = (): void => {
    moved = true;
    national = false;
    // Someone is moving the map: show it now, finished or not.
    goLive();
  };
  const onMoveStart = (event: MapMovementEvent): void => {
    if (event.originalEvent !== undefined) onUserMove();
  };
  function fitContinentalUs(options: { animate?: boolean } = {}): void {
    national = true;
    map.fitBounds(bounds, {
      padding: fitPadding(),
      animate: options.animate ?? false,
    });
  }
  function goTo(target: MapView | null): void {
    if (target === null) {
      fitContinentalUs();
      return;
    }
    national = false;
    const allowed = constrainView(limits, target);
    map.jumpTo({ center: [allowed.lon, allowed.lat], zoom: allowed.zoom });
  }
  /**
   * New limits for the window's new size, applied before anything is drawn at
   * it: the view moves to the nearest allowed one, and the national view is
   * fitted afresh.
   */
  const onResize = (): void => {
    limits = viewLimits(size(), fitPadding());
    map.setTransformConstrain(constrainer(limits));
    map.setMinZoom(limits.minZoom);
    if (national) fitContinentalUs();
  };
  map.on('movestart', onMoveStart);
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
    fitContinentalUs,
    goTo,
    destroy() {
      map.remove();
      container.classList.remove(LIVE_CLASS);
    },
  };
}

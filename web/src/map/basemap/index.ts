import './maplibre.css';

import type { Map as MapLibreMap, MapMovementEvent, PaddingOptions } from 'maplibre-gl';

import { mapLocale } from '../../copy';
import { collapsedAttribution } from './attribution';
import type { MapLibre } from './maplibre';
import { OPENFREEMAP_ATTRIBUTION, registerOpenFreeMap } from './openfreemap';
import { afterNextFrame, LIVE_CLASS, markStep, whenGpuIdle } from './reveal';
import { BASEMAP_IDS, buildBasemapStyle } from './style';
import type { BasemapLook, UsLinesData } from './style';
import { US_BOUNDS } from './us-geo';

export { BASEMAP_IDS } from './style';
export { US_BOUNDS } from './us-geo';

export interface BasemapOptions {
  /** Element the map fills. */
  container: HTMLElement;
  /**
   * Element whose box the continental US is fitted into at the initial view.
   * The inline still in index.html is drawn inside the same box, which is what
   * makes the handover invisible.
   */
  frame: HTMLElement;
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
  /** True once someone has moved the map. Until then it refits when the window resizes. */
  readonly moved: boolean;
  /** Fits the continental US into the frame, as at the initial view. */
  fitContinentalUs(options?: { animate?: boolean }): void;
  destroy(): void;
}

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
export function framePadding(container: Element, frame: Element): PaddingOptions {
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
  maplibre,
  workerUrl,
  usLines,
}: BasemapOptions & BasemapResources): Basemap {
  configure(maplibre, workerUrl);
  const bounds = new maplibre.LngLatBounds(
    [US_BOUNDS[0], US_BOUNDS[1]],
    [US_BOUNDS[2], US_BOUNDS[3]],
  );

  const map = new maplibre.Map({
    container,
    style: buildBasemapStyle({ usLines, ...look() }),
    locale: mapLocale,
    bounds,
    fitBoundsOptions: { padding: framePadding(container, frame) },
    attributionControl: false,
    maplibreLogo: false,
    minZoom: 1,
    maxZoom: 16,
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

  const onMoveStart = (event: MapMovementEvent): void => {
    if (event.originalEvent === undefined) return;
    moved = true;
    // Someone is moving the map: show it now, finished or not.
    goLive();
  };
  const refit = (): void => {
    if (!moved) fitContinentalUs();
  };
  function fitContinentalUs(options: { animate?: boolean } = {}): void {
    map.fitBounds(bounds, {
      padding: framePadding(container, frame),
      animate: options.animate ?? false,
    });
  }
  map.on('movestart', onMoveStart);
  map.on('resize', refit);

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
    fitContinentalUs,
    destroy() {
      map.remove();
      container.classList.remove(LIVE_CLASS);
    },
  };
}

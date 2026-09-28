/**
 * The GPU work of the map's start, each part in a task of its own.
 *
 * Creating a WebGL context, turning on the extensions MapLibre asks for, and
 * building each program it draws with all have the page wait on the GPU
 * process. Done where MapLibre does them, the waits add to the work around
 * them in a few long tasks: its constructor, and the frames that first draw
 * the ground, the lines and the names. Done here first, each is a short task
 * of its own, and MapLibre finds the context and the programs ready.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import { whenGpuIdle, yieldToMain } from './reveal';

/**
 * The context MapLibre asks for (maplibre-gl 6.11 Map._setupPainter: its
 * default canvasContextAttributes, with alpha, depth, stencil and
 * premultiplied alpha). A canvas hands out the context it already has
 * whatever is asked, so these only have to be what MapLibre would get.
 */
export const MAP_CONTEXT_ATTRIBUTES: WebGLContextAttributes = {
  antialias: false,
  preserveDrawingBuffer: false,
  powerPreference: 'high-performance',
  failIfMajorPerformanceCaveat: false,
  desynchronized: false,
  alpha: true,
  depth: true,
  stencil: true,
  premultipliedAlpha: true,
};

/** MapLibre's largest canvas side, in device pixels (its default maxCanvasSize). */
const MAX_CANVAS_SIDE = 4096;

/**
 * A canvas the size MapLibre will make it, with its WebGL2 context made and
 * the extensions and limits MapLibre's Context reads as it starts already
 * read (maplibre-gl 6.11 Context constructor); null where there is no WebGL2,
 * for MapLibre to fail on as it would anyway.
 *
 * The context is made in the task this is called in; the GPU process then
 * sets it up while the page waits for it without blocking (reveal.ts
 * whenGpuIdle), and the extensions are read in a later task, without a wait.
 */
export async function prepareCanvas(
  size: { readonly width: number; readonly height: number },
  pixelRatio: number,
): Promise<HTMLCanvasElement | null> {
  const ratio = Math.min(
    pixelRatio,
    MAX_CANVAS_SIDE / Math.max(1, size.width),
    MAX_CANVAS_SIDE / Math.max(1, size.height),
  );
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(size.width * ratio);
  canvas.height = Math.round(size.height * ratio);
  const gl = canvas.getContext('webgl2', MAP_CONTEXT_ATTRIBUTES);
  if (gl === null) return null;
  await whenGpuIdle(gl);
  // Each extension has the page wait on the GPU process as it turns it on: one a task.
  const anisotropic = gl.getExtension('EXT_texture_filter_anisotropic');
  if (anisotropic !== null) gl.getParameter(anisotropic.MAX_TEXTURE_MAX_ANISOTROPY_EXT);
  gl.getParameter(gl.MAX_TEXTURE_SIZE);
  await yieldToMain();
  gl.getExtension('EXT_color_buffer_half_float');
  await yieldToMain();
  gl.getExtension('EXT_color_buffer_float');
  return canvas;
}

/**
 * Runs `create` with `canvas` as the first canvas the document creates
 * meanwhile: MapLibre's constructor creates its own with
 * document.createElement, and takes this one instead. With null, or once
 * `create` has returned or thrown, the document creates canvases as usual.
 * A canvas `create` did not take has its context released.
 */
export function withCanvas<T>(canvas: HTMLCanvasElement | null, create: () => T): T {
  if (canvas === null) return create();
  const spare: { canvas: HTMLCanvasElement | null } = { canvas };
  // The document's own method, from its prototype: the property set below shadows it.
  const original: (
    this: Document,
    tagName: string,
    options?: ElementCreationOptions,
  ) => HTMLElement = Reflect.get(Document.prototype, 'createElement');
  const createElement = (tagName: string, options?: ElementCreationOptions): HTMLElement =>
    original.call(document, tagName, options);
  Object.defineProperty(document, 'createElement', {
    configurable: true,
    writable: true,
    value: (tagName: string, options?: ElementCreationOptions): HTMLElement => {
      const taken = spare.canvas;
      if (taken !== null && tagName.toLowerCase() === 'canvas') {
        spare.canvas = null;
        return taken;
      }
      return createElement(tagName, options);
    },
  });
  try {
    return create();
  } finally {
    // The document's own createElement again: the property set above goes.
    delete (document as { createElement?: unknown }).createElement;
    spare.canvas?.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext();
  }
}

/**
 * The programs MapLibre draws every frame with from its first (maplibre-gl
 * 6.11 Painter.render): the ground's, and the stencil's clipping masks'.
 */
const FIRST_PROGRAMS = ['background', 'clippingMask'] as const;

/**
 * Has MapLibre build the programs its first frame draws with, one per call
 * of `schedule` (a task each), once its style is in: building a program has
 * the page wait on the GPU process, and all of them in the first frame would
 * make that frame one long task. A program built here is the one the frame
 * takes from MapLibre's cache; one not built in time is built as it draws.
 */
export function warmFirstPrograms(
  map: Pick<MapLibreMap, 'painter' | 'style'>,
  schedule: (run: () => void) => void,
): void {
  for (const name of FIRST_PROGRAMS) {
    schedule(() => {
      const painter = map.painter as Omit<MapLibreMap['painter'], 'style'> & {
        style?: MapLibreMap['style'];
      };
      try {
        // The painter reads the style as it builds a program; it takes it on at its first frame.
        painter.style ??= map.style;
        painter.useProgram(name);
      } catch {
        // Not ready, or gone: MapLibre builds it as it first draws.
      }
    });
  }
}

/** The tile a sourcedata event is about, with its buckets by layer, when it is one. */
interface LoadedTile {
  readonly buckets?: Readonly<Record<string, unknown>>;
}

/** What a bucket keeps of the programs it is drawn with (maplibre-gl 6.11 buckets). */
interface ConfiguredBucket {
  readonly programConfigurations?: { get(layerId: string): unknown };
  readonly text?: { readonly programConfigurations?: { get(layerId: string): unknown } };
  readonly iconsInText?: boolean;
}

/** The program MapLibre draws a line with when it has no dashes, pattern or gradient. */
const PLAIN_LINE_PAINT = ['line-dasharray', 'line-pattern', 'line-gradient'] as const;

/**
 * As each tile comes in, has MapLibre build the programs its lines and names
 * are drawn with, each once, in a task of its own (`schedule`) ahead of the
 * frame that first draws them: plain lines ('line') and names ('symbolSDF'),
 * with the tile's own program configuration, as MapLibre's drawLine and
 * drawSymbols ask for them (maplibre-gl 6.11). Anything else is built as it
 * is first drawn. Returns a function that stops.
 */
export function warmTilePrograms(
  map: MapLibreMap,
  schedule: (run: () => void) => void,
): () => void {
  const warmed = new Set<string>();
  const warm = (name: string, configuration: unknown): void => {
    const key = `${name}${String((configuration as { cacheKey?: unknown } | null)?.cacheKey)}`;
    if (warmed.has(key)) return;
    warmed.add(key);
    schedule(() => {
      const painter = map.painter as Omit<MapLibreMap['painter'], 'style'> & {
        style?: MapLibreMap['style'];
      };
      try {
        painter.style ??= map.style;
        painter.useProgram(name, configuration as Parameters<typeof painter.useProgram>[1]);
      } catch {
        // Not ready, or gone: MapLibre builds it as it first draws.
      }
    });
  };
  const onData = (event: { tile?: unknown }): void => {
    const buckets = (event.tile as LoadedTile | undefined)?.buckets;
    if (buckets === undefined) return;
    for (const [id, value] of Object.entries(buckets)) {
      const bucket = value as ConfiguredBucket;
      try {
        const type = map.getLayer(id)?.type;
        if (
          type === 'line' &&
          PLAIN_LINE_PAINT.every((name) => map.getPaintProperty(id, name) === undefined)
        ) {
          const configuration = bucket.programConfigurations?.get(id);
          if (configuration !== undefined) warm('line', configuration);
        } else if (
          type === 'symbol' &&
          bucket.iconsInText !== true &&
          map.getLayoutProperty(id, 'text-field') !== undefined
        ) {
          const configuration = bucket.text?.programConfigurations?.get(id);
          if (configuration !== undefined) warm('symbolSDF', configuration);
        }
      } catch {
        // A layer gone meanwhile: nothing to build.
      }
    }
  };
  map.on('sourcedata', onData);
  return () => {
    map.off('sourcedata', onData);
  };
}

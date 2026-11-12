/**
 * Closings announced for later days on the map (the owner's "rings"): at
 * each school with a closing on a day after its map day, and no light today,
 * a quiet dashed ring from a close zoom in (LATER_RINGS_FROM), loaded with
 * the first later day the live file names (app/boot.ts), never in the page's
 * first script.
 *
 * The ring never reads as a light:
 * - a thin dashed ring in the theme's second gray, with no glow and no halo,
 *   no wider than today's glyph at any zoom (GLYPH_RADIUS_STOPS), around a
 *   small, see-through mark of its status (a dot, a ring, a diamond or a half
 *   dot) far weaker than a light's;
 * - drawn under the glow in either of its places (BASEMAP_IDS.glowSlot and
 *   glowSlotFlat), so today's light always draws over it; the light around
 *   the school's own dot gives way to it (SCHOOL_LATER_STATE), so it has no
 *   light of its own, and the dot is under the ring's ground, which hides it;
 *   from the zoom every ring is drawn the dot gives way to it too
 *   (basemap/schools.ts RINGED_DOT), so where a ring gives way to a label
 *   further out its school keeps its plain dot, never a blank;
 * - none from the regional view out, so a storm's lights today stay what the
 *   eye sees there.
 * A school lit today has no ring: its light wins, and its later days are in
 * its panel. Nor has a school at its place, which the glow covers
 * (data/later-days.ts). A ring near today's light gives way to the light's
 * glow as the map draws it at the zoom (lightClearZoom): until the zoom
 * parts them its school keeps its plain dot, as any neighbour of a light,
 * so no ring shows through today's light at any zoom. A ring never takes a
 * place name's room: across a county
 * (LATER_RINGS and LATER_RINGS_NEAR, to the zoom school names come in at) a
 * ring that would run into a label is not drawn there, as labels give way to
 * each other, and the name stays; closer in (LATER_RINGS_CLOSE) every ring is drawn, and the
 * names keep clear of its school's dot as of every school's
 * (basemap/schools.ts schoolSpaceLayer). A tap on a ring is a tap on its
 * school's dot (map/school-taps.ts).
 */

import type { FilterSpecification, GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';

import type { Directory } from '../data/directory';
import { NEAR_REACH } from '../data/later-days';
import type { LaterMark } from '../data/later-days';
import { THEME_EVENT } from '../theme/event';
import {
  BASEMAP_IDS,
  SCHOOLS_TILE_LAYER,
  SCHOOL_LATER_FROM,
  SCHOOL_LATER_STATE,
  SCHOOL_LATER_WHOLE,
} from './basemap/ids';
import { MAX_ZOOM } from './basemap/bounds';
import { SCHOOL_FADE, SCHOOL_LATER_ZOOMS, SCHOOL_NAMES_FROM } from './basemap/schools';
import { fallbackHalo, glowReachPx, glowStyleAtZoom, interpolateStops } from './glow/curves';

/**
 * The zoom the rings come in from, faded in by LATER_RINGS_WHOLE: a county and
 * closer, every school on its own, as the glow's dust gives way to the school
 * dots (basemap/dots.ts SCHOOL_DUST_UNTIL).
 */
export const LATER_RINGS_FROM = SCHOOL_LATER_FROM;
export const LATER_RINGS_WHOLE = SCHOOL_LATER_WHOLE;
/** The zoom every ring is drawn from, as the school names come in and keep clear of the dots. */
export const LATER_RINGS_ALWAYS = SCHOOL_NAMES_FROM - SCHOOL_FADE;

export const LATER_SOURCE = 'later-days';
/**
 * The rings across a county with no light near: each one drawn only where no
 * label has its room, fading in by the zoom alone.
 */
export const LATER_RINGS = 'later-rings';
/** The same for the rings near today's lights: each from the zoom it is clear of them. */
export const LATER_RINGS_NEAR = 'later-rings-near';
/** The rings closer in: every one, each from the zoom it is clear of today's lights. */
export const LATER_RINGS_CLOSE = 'later-rings-close';
/** All three, as the map draws them, further out first. */
export const LATER_RING_LAYERS = [LATER_RINGS, LATER_RINGS_NEAR, LATER_RINGS_CLOSE] as const;

/** The ring's radius at icon-size 1, CSS px: today's glyph's at zoom 11 (glow/curves.ts). */
export const RING_RADIUS = 4.5;
/** The radius of the ground under the ring, over the school's dot, at icon-size 1, CSS px. */
export const RING_GROUND_RADIUS = RING_RADIUS - 0.4;
/** The image's side, CSS px: the ring and a pixel to spare. */
const SIDE = 11;
/** Each image's pixels to a CSS pixel: sharp on a phone's screen. */
const RATIO = 3;
/**
 * The ring's size by zoom as a share of RING_RADIUS: today's glyph radius
 * (glow/curves.ts GLYPH_RADIUS_STOPS: 4.5 at 11, 5.5 at 14, 6.5 at 17) and
 * never more; before the glyphs come in, its size at 11, no wider than a light's flat disc or
 * core and halo there.
 */
const SIZE_STOPS: readonly (readonly [number, number])[] = [
  [LATER_RINGS_FROM, 1],
  [11, 1],
  [14, 5.5 / RING_RADIUS],
  [17, 6.5 / RING_RADIUS],
];

/** The ring's drawn radius at `zoom`, CSS px. */
export function ringRadiusPx(zoom: number): number {
  return RING_RADIUS * interpolateStops(SIZE_STOPS, zoom);
}

/**
 * How far a lone light the map shows today is drawn out from its school at
 * `zoom`, CSS px, on whichever path a device draws the glow on: its glow's
 * reach (glow/curves.ts glowReachPx), its own halo, or the wider halo the
 * 8-bit fallback draws in their place (fallbackHalo), whichever is widest,
 * past its glyph (wider than any). The fallback's is the widest from the zoom
 * the rings come in at to 11, and wider there than the faint haze the bloom
 * leaves on the float path (20 px out at 9.75 in the dark look).
 */
export function lightReachPx(zoom: number): number {
  const style = glowStyleAtZoom(zoom);
  return Math.max(glowReachPx(zoom), style.haloRadiusPx, fallbackHalo(style, zoom).radiusPx);
}

/** The zooms the clear test looks at, each this far apart: far finer than the zooms a ring comes in at. */
const CLEAR_TEST_STEP = 1 / 32;
/** Each test zoom's least distance in CSS px between a ring's school and a light's, clear of it. */
let clearTable: readonly (readonly [zoom: number, px: number])[] | null = null;

/**
 * The zoom a ring `near` today's light (data/later-days.ts LaterMark.near) is
 * drawn whole from: the first of the whole zooms a ring can be whole at
 * (basemap/schools.ts SCHOOL_LATER_ZOOMS) a whole zoom or more past the last
 * zoom the ring and the light's drawn glow overlap at. The map draws a ring's
 * opacity, which reads both the zoom and the ring's own `clear`, as it is at
 * the tile's whole zoom and the next, blended between them, so a ring whole
 * at c is drawn, fading in, from c - 1, and it is clear of the light there
 * already. LATER_RINGS_WHOLE where no light is that near at any zoom (its
 * ring comes in by the zoom alone, on its own layer); Infinity where they
 * overlap too near the map's closest, so the school keeps its plain dot.
 */
export function lightClearZoom(near: number): number {
  if (!(near < NEAR_REACH)) return LATER_RINGS_WHOLE;
  clearTable ??= Array.from(
    { length: Math.round((MAX_ZOOM - LATER_RINGS_FROM) / CLEAR_TEST_STEP) + 1 },
    (_, i) => {
      const zoom = LATER_RINGS_FROM + i * CLEAR_TEST_STEP;
      return [zoom, lightReachPx(zoom) + ringRadiusPx(zoom)] as const;
    },
  );
  let touches = -Infinity;
  for (const [zoom, px] of clearTable) if (near * 2 ** zoom < px) touches = zoom;
  if (touches === -Infinity) return LATER_RINGS_WHOLE;
  // Past the last test zoom it touches at and the step after it, which the test does not look in.
  return SCHOOL_LATER_ZOOMS.find((zoom) => zoom - 1 >= touches + CLEAR_TEST_STEP) ?? Infinity;
}

/** The statuses' color tokens, by status code (closed, delayed, remote, early dismissal). */
const STATUS_TOKENS = [
  '--status-closed',
  '--status-delayed',
  '--status-remote',
  '--status-early-dismissal',
] as const;

/** The image of a status's ring. */
export function ringImageId(status: number): string {
  return `later-ring-${String(status)}`;
}

/** The colors a ring is drawn in, read from the page's theme. */
export interface RingColors {
  /** The dashes. */
  readonly ring: string;
  /** Under the ring, over the school's own dot: the map's ground. */
  readonly ground: string;
  /** Each status's color, by code. */
  readonly status: readonly string[];
  /** How strong the status's mark is: far weaker than a light's. */
  readonly markAlpha: number;
  /** How strong the dashes are. */
  readonly ringAlpha: number;
}

function token(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = style.getPropertyValue(name).trim();
  return value === '' ? fallback : value;
}

/** The theme's colors for the rings, from the page's tokens. */
export function ringColors(root: Element = document.documentElement): RingColors {
  const style = getComputedStyle(root);
  return {
    ring: token(style, '--text-2', '#a3a3a3'),
    ground: token(style, '--map-ground', token(style, '--bg', '#000')),
    status: STATUS_TOKENS.map((name) => token(style, name, '#7fd4ff')),
    // As strong as before at 0.9 of the layer, which is drawn whole now, so its ground hides
    // the school's dot under it entirely: 0.85 and 0.6 of 0.9.
    markAlpha: 0.54,
    ringAlpha: 0.765,
  };
}

/**
 * The status's small mark at the ring's middle: a dot, a ring, a diamond or a
 * half dot, as the key draws them, at about a third of a glyph's size.
 */
function drawMark(ctx: CanvasRenderingContext2D, status: number, c: number, color: string): void {
  // Wide enough to read as round on a screen with a pixel to a CSS pixel, and weak (markAlpha).
  const r = 1.85;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.9;
  ctx.beginPath();
  if (status === 1) {
    ctx.arc(c, c, r + 0.2, 0, Math.PI * 2);
    ctx.stroke();
  } else if (status === 2) {
    const d = r * 1.25;
    ctx.moveTo(c, c - d);
    ctx.lineTo(c + d, c);
    ctx.lineTo(c, c + d);
    ctx.lineTo(c - d, c);
    ctx.closePath();
    ctx.fill();
  } else if (status === 3) {
    ctx.arc(c, c, r + 0.2, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(c, c, r + 0.2, Math.PI / 2, (Math.PI * 3) / 2);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.arc(c, c, r, 0, Math.PI * 2);
    ctx.fill();
  }
}

/** A status's ring as an image: the ground over the school's dot, the dashes, the mark. */
export function ringImage(status: number, colors: RingColors): ImageData | null {
  const canvas = document.createElement('canvas');
  canvas.width = SIDE * RATIO;
  canvas.height = SIDE * RATIO;
  const ctx = canvas.getContext('2d');
  if (ctx === null) return null;
  ctx.scale(RATIO, RATIO);
  const c = SIDE / 2;
  // The ground under it all, so the school's white dot never shows through its middle.
  ctx.beginPath();
  ctx.arc(c, c, RING_GROUND_RADIUS, 0, Math.PI * 2);
  ctx.fillStyle = colors.ground;
  ctx.fill();
  // Eight thin dashes in the second gray, with no glow.
  ctx.lineWidth = 1.25;
  ctx.strokeStyle = colors.ring;
  ctx.globalAlpha = colors.ringAlpha;
  const dashes = 8;
  const step = (Math.PI * 2) / dashes;
  for (let i = 0; i < dashes; i++) {
    ctx.beginPath();
    ctx.arc(c, c, RING_RADIUS - 0.5, i * step + step * 0.18, i * step + step * 0.72);
    ctx.stroke();
  }
  ctx.globalAlpha = colors.markAlpha;
  drawMark(ctx, status, c, colors.status[status] ?? colors.status[0] ?? '#7fd4ff');
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

/** The rings as a GeoJSON source's data. */
export interface RingCollection {
  readonly type: 'FeatureCollection';
  readonly features: readonly {
    readonly type: 'Feature';
    readonly properties: {
      readonly id: string;
      readonly status: number;
      readonly day: string;
      /** The zoom it is drawn whole from (lightClearZoom). */
      readonly clear: number;
    };
    readonly geometry: { readonly type: 'Point'; readonly coordinates: readonly [number, number] };
  }[];
}

/**
 * The marks as map features: each at its school's place, with its status, day
 * and the zoom it is drawn whole from; none for a mark today's light is too
 * near at every zoom.
 */
export function ringFeatures(
  marks: readonly LaterMark[],
  directory: Pick<Directory, 'lngLat' | 'meta'>,
): RingCollection {
  return {
    type: 'FeatureCollection',
    features: clearMarks(marks).map(([mark, clear]) => ({
      type: 'Feature',
      properties: {
        id: directory.meta.ids[mark.school] ?? '',
        status: mark.status,
        day: mark.day,
        clear,
      },
      geometry: {
        type: 'Point',
        coordinates: [
          directory.lngLat[mark.school * 2] ?? 0,
          directory.lngLat[mark.school * 2 + 1] ?? 0,
        ],
      },
    })),
  };
}

/** Each mark drawn at some zoom, with the zoom it is drawn whole from (lightClearZoom). */
function clearMarks(marks: readonly LaterMark[]): (readonly [LaterMark, number])[] {
  return marks
    .map((mark) => [mark, lightClearZoom(mark.near)] as const)
    .filter(([, clear]) => clear !== Infinity);
}

/**
 * A ring's opacity by zoom, for a ring with no light near: fading in by the
 * zoom alone, from LATER_RINGS_FROM to LATER_RINGS_WHOLE. Read with the zoom
 * only, the map draws it at the zoom it is at.
 */
function freeOpacity(): unknown {
  return byZoom([
    [LATER_RINGS_FROM, 0],
    [LATER_RINGS_WHOLE, 1],
  ]);
}

/**
 * A ring's opacity by zoom: none until the whole zoom it is drawn whole from
 * (its feature's `clear`), and whole from it. Read with the ring's own
 * `clear`, the map draws it as it is at the tile's whole zoom and the next,
 * blended between them: fading in over the zoom before `clear`, and only at
 * whole zooms, so stops at whole zooms are what it draws.
 */
function clearOpacity(): unknown {
  return [
    'interpolate',
    ['linear'],
    ['zoom'],
    ...SCHOOL_LATER_ZOOMS.flatMap((zoom) => [zoom, ['case', ['<=', ['get', 'clear'], zoom], 1, 0]]),
  ];
}

function byZoom(stops: readonly (readonly [number, number])[]): unknown {
  return ['interpolate', ['linear'], ['zoom'], ...stops.flat()];
}

/** A ring layer's spec, as ringLayers gives it. */
export interface RingLayer {
  readonly id: string;
  readonly type: 'symbol';
  readonly source: string;
  readonly minzoom: number;
  readonly maxzoom?: number;
  readonly filter?: FilterSpecification;
  readonly layout: Readonly<Record<string, unknown>>;
  readonly paint: Readonly<Record<string, unknown>>;
}

/**
 * The three ring layers. Across a county (to LATER_RINGS_ALWAYS) a ring is
 * placed after every label over it and gives way to them (allow-overlap off),
 * so no name is dropped or crossed for a ring; it takes no room itself
 * (ignore-placement), so no ring hides another or a label under it. There a
 * ring with no light near fades in by the zoom alone (LATER_RINGS), and one
 * near today's light from the zoom it is clear of the light (LATER_RINGS_NEAR,
 * lightClearZoom). Closer in every ring is drawn, each from the zoom it is
 * clear of the lights: the names keep clear of each school's dot there.
 */
export function ringLayers(): readonly RingLayer[] {
  const layout = (yields: boolean): Record<string, unknown> => ({
    'icon-image': ['concat', 'later-ring-', ['to-string', ['get', 'status']]],
    'icon-size': byZoom(SIZE_STOPS),
    'icon-allow-overlap': !yields,
    'icon-ignore-placement': true,
    'icon-padding': 0,
    'icon-rotation-alignment': 'viewport',
    'icon-pitch-alignment': 'viewport',
  });
  return [
    {
      id: LATER_RINGS,
      type: 'symbol',
      source: LATER_SOURCE,
      minzoom: LATER_RINGS_FROM,
      maxzoom: LATER_RINGS_ALWAYS,
      filter: ['==', ['get', 'clear'], LATER_RINGS_WHOLE],
      layout: layout(true),
      paint: { 'icon-opacity': freeOpacity() },
    },
    {
      id: LATER_RINGS_NEAR,
      type: 'symbol',
      source: LATER_SOURCE,
      minzoom: LATER_RINGS_WHOLE,
      maxzoom: LATER_RINGS_ALWAYS,
      filter: ['>', ['get', 'clear'], LATER_RINGS_WHOLE],
      layout: layout(true),
      paint: { 'icon-opacity': clearOpacity() },
    },
    {
      id: LATER_RINGS_CLOSE,
      type: 'symbol',
      source: LATER_SOURCE,
      minzoom: LATER_RINGS_ALWAYS,
      layout: layout(false),
      paint: { 'icon-opacity': clearOpacity() },
    },
  ];
}

export interface LaterRings {
  /** Shows these rings, at their schools' places in `directory`; none with none. */
  show(marks: readonly LaterMark[], directory: Pick<Directory, 'lngLat' | 'meta'> | null): void;
  remove(): void;
}

/** The later-day rings on `map`, under its lights and over its school dots. */
export function startLaterRings(map: MapLibreMap): LaterRings {
  let data: RingCollection = { type: 'FeatureCollection', features: [] };
  let removed = false;
  /**
   * The schools with a ring, each with the zoom it is drawn whole from, and those whose dot is
   * marked so (SCHOOL_LATER_STATE).
   */
  let wanted: ReadonlyMap<number, number> = new Map();
  let marked: ReadonlyMap<number, number> = new Map();
  /** Each ringed school's own dot, and its light, give way to its ring (basemap/schools.ts). */
  const markDots = (): void => {
    const source = BASEMAP_IDS.schoolsSource;
    if (wanted === marked || map.getSource(source) === undefined) return;
    const target = { source, sourceLayer: SCHOOLS_TILE_LAYER, id: 0 };
    for (const id of marked.keys()) {
      if (wanted.has(id)) continue;
      target.id = id;
      map.removeFeatureState(target, SCHOOL_LATER_STATE);
    }
    for (const [id, clear] of wanted) {
      if (marked.get(id) === clear) continue;
      target.id = id;
      map.setFeatureState(target, { [SCHOOL_LATER_STATE]: clear });
    }
    marked = wanted;
  };

  const addImages = (): void => {
    const colors = ringColors();
    for (let status = 0; status < STATUS_TOKENS.length; status++) {
      const image = ringImage(status, colors);
      if (image === null) continue;
      const id = ringImageId(status);
      if (map.hasImage(id)) map.updateImage(id, image);
      else map.addImage(id, image, { pixelRatio: RATIO });
    }
  };

  /** Puts the source and layers on the map's style, where they are not on it yet. */
  /** Whether ensure is under way: adding an image or a layer fires the event that calls it. */
  let ensuring = false;
  const ensure = (): void => {
    if (ensuring || removed || map.getLayer(BASEMAP_IDS.glowSlotFlat) === undefined) return;
    ensuring = true;
    try {
      put();
    } finally {
      ensuring = false;
    }
  };
  const put = (): void => {
    if (map.getSource(LATER_SOURCE) === undefined) {
      addImages();
      map.addSource(LATER_SOURCE, { type: 'geojson', data: data as never });
    }
    // Right over the school dots, under the glow in either of its places: further out, each ring
    // only where it runs into no label; closer in, every ring.
    for (const layer of ringLayers()) {
      if (map.getLayer(layer.id) !== undefined) continue;
      map.addLayer(
        hidden ? { ...layer, layout: { ...layer.layout, visibility: 'none' } } : layer,
        BASEMAP_IDS.glowSlotFlat,
      );
    }
  };

  /**
   * Whether the rings are hidden while new ones are on their way: today's lights are lit
   * again before the rings' data, which goes through a worker, reaches the map, so until it
   * has, a ring could show where a new light now is. Each change of rings is counted, so
   * only the last one shows them again.
   */
  let hidden = false;
  let changes = 0;
  const setHidden = (hide: boolean): void => {
    hidden = hide;
    for (const id of LATER_RING_LAYERS) {
      if (map.getLayer(id) !== undefined) {
        map.setLayoutProperty(id, 'visibility', hide ? 'none' : 'visible');
      }
    }
  };
  /** Shows the rings again once the map holds this change's rings, every tile of them. */
  const showOnceIn = (change: number): void => {
    const check = (): void => {
      if (change !== changes || removed) {
        map.off('sourcedata', check);
        return;
      }
      if (map.getSource(LATER_SOURCE) !== undefined && !map.isSourceLoaded(LATER_SOURCE)) return;
      map.off('sourcedata', check);
      setHidden(false);
    };
    map.on('sourcedata', check);
    check();
  };

  const onStyle = (): void => {
    ensure();
    markDots();
  };
  // A theme put on: the rings drawn again in its colors.
  const onTheme = (): void => {
    if (map.getSource(LATER_SOURCE) !== undefined) addImages();
  };
  map.on('styledata', onStyle);
  document.addEventListener(THEME_EVENT, onTheme);
  ensure();

  return {
    show(marks, directory) {
      const next: RingCollection =
        directory === null
          ? { type: 'FeatureCollection', features: [] }
          : ringFeatures(marks, directory);
      const changed = JSON.stringify(next.features) !== JSON.stringify(data.features);
      data = next;
      // A source put on now holds these rings already.
      const fresh = map.getSource(LATER_SOURCE) === undefined;
      ensure();
      const source = map.getSource<GeoJSONSource>(LATER_SOURCE);
      if (!fresh && changed && source !== undefined) {
        // Hidden in this same turn, before the map draws today's lights lit again.
        setHidden(true);
        const change = ++changes;
        const showAgain = (): void => {
          showOnceIn(change);
        };
        source.setData(data).then(showAgain, showAgain);
      }
      wanted = new Map(
        directory === null ? [] : clearMarks(marks).map(([mark, clear]) => [mark.school, clear]),
      );
      markDots();
    },
    remove() {
      removed = true;
      wanted = new Map();
      markDots();
      map.off('styledata', onStyle);
      document.removeEventListener(THEME_EVENT, onTheme);
      for (const id of LATER_RING_LAYERS) if (map.getLayer(id) !== undefined) map.removeLayer(id);
      if (map.getSource(LATER_SOURCE) !== undefined) map.removeSource(LATER_SOURCE);
    },
  };
}

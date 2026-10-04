/**
 * Dust: every school as a small, faint speck, drawn by the glow layer at the
 * zooms the map's own school dots are not (basemap/dots.ts), under the glow's
 * light, which is screened over it.
 *
 * One point sprite per school, from one buffer of positions: a school the
 * glow lights is moved off the world in it (DUST_HIDDEN_Y), so its speck
 * gives way to its light. The schools are sorted into a grid of cells over
 * the world, row by row, so a frame draws only the rows of cells in view,
 * one run of the buffer each: across a state, a sixth of the country's
 * schools, and across a metro a few thousand. Each speck is a disc with a soft edge: as MapLibre
 * edges a circle (over the pixel inside its radius) where it draws over the
 * map's own dots, and a pixel wider further out, so a far speck, under a
 * pixel across, reads as a fainter point rather than twinkling in and out
 * between pixels as the map moves.
 *
 * Specks are drawn keeping the brighter of speck and map at each pixel (MAX
 * blending), never their sum: where a city's schools crowd, the dust is a
 * haze no brighter than one speck, never a white blob to rival the lights;
 * and over one of the map's own dots, the same dot drawn again looks the
 * same as once.
 */
import { type ZoomStops, interpolateStops } from './curves';
import { mercatorXFromLng, mercatorYFromLat } from './mercator';

export interface DustStyle {
  /** Zooms it is drawn at: from `from` up to, not including, `until`. */
  readonly from: number;
  readonly until: number;
  /** A speck's radius, CSS px, by zoom. */
  readonly radius: ZoomStops;
  /** Its opacity by zoom. */
  readonly opacity: ZoomStops;
  /**
   * How soft its edge is by zoom: 0 edges it over the pixel inside its
   * radius, as MapLibre edges a circle; 1 reaches a pixel past its radius.
   */
  readonly softness: ZoomStops;
  /** Its color, sRGB channels 0..1. */
  readonly color: readonly [r: number, g: number, b: number];
}

/** How the dust is drawn at one zoom. */
export interface DustAtZoom {
  /** Radius, CSS px. */
  readonly radius: number;
  readonly opacity: number;
  /** 0 to 1, as DustStyle's softness. */
  readonly softness: number;
}

/** The dust at `zoom`, or null where none is drawn. */
export function dustAtZoom(style: DustStyle, zoom: number): DustAtZoom | null {
  if (!(zoom >= style.from && zoom < style.until)) return null;
  const opacity = interpolateStops(style.opacity, zoom);
  const radius = interpolateStops(style.radius, zoom);
  const softness = Math.min(1, Math.max(0, interpolateStops(style.softness, zoom)));
  return opacity > 0 && radius > 0 ? { radius, opacity, softness } : null;
}

/**
 * Sprite size, device px, for a speck of `radius` device px and its edge's
 * softness: just room for every pixel it covers, as each fragment costs a
 * software rasterizer time.
 */
export function dustSpriteSize(radius: number, softness: number): number {
  return 2 * (radius + softness);
}

/**
 * How much of a speck's color a pixel `d` device px from its center takes,
 * for a speck of `radius` device px (the shader's own formula): all of it up
 * to a pixel inside its radius, easing to none at `radius + softness`.
 */
export function dustCover(d: number, radius: number, softness: number): number {
  const inner = radius - 1;
  const outer = radius + softness;
  const t = Math.min(1, Math.max(0, (d - inner) / (outer - inner)));
  return 1 - t * t * (3 - 2 * t);
}

/** Cells across the world, each way: 256, a cell 2 px across at zoom 0 and 180 px at zoom 6.5. */
export const DUST_GRID = 256;

/** The schools sorted into the grid's cells, row by row. */
export interface DustGrid {
  /**
   * Interleaved float32 Web Mercator x, y, in cell order. Float32 is exact
   * enough for dust, drawn only across a metro and further out: about a
   * hundredth of a pixel at zoom 10.
   */
  readonly positions: Float32Array;
  /** Each school's place in `positions`, by its place in the list given, and back. */
  readonly slotOf: Uint32Array;
  readonly order: Uint32Array;
  /** Where each cell's schools start in `positions`, row by row, and where the last ends. */
  readonly cellStart: Uint32Array;
}

function cellOf(value: number): number {
  return Math.min(DUST_GRID - 1, Math.max(0, Math.floor(value * DUST_GRID)));
}

/** Sorts schools, as longitude, latitude pairs in degrees, into the grid's cells. */
export function dustGrid(lngLat: Float32Array | Float64Array): DustGrid {
  const count = Math.floor(lngLat.length / 2);
  const x = new Float64Array(count);
  const y = new Float64Array(count);
  const cell = new Uint32Array(count);
  const cellStart = new Uint32Array(DUST_GRID * DUST_GRID + 1);
  for (let i = 0; i < count; i++) {
    x[i] = mercatorXFromLng(lngLat[i * 2] ?? 0);
    y[i] = mercatorYFromLat(lngLat[i * 2 + 1] ?? 0);
    const key = cellOf(y[i] ?? 0) * DUST_GRID + cellOf(x[i] ?? 0);
    cell[i] = key;
    cellStart[key + 1] = (cellStart[key + 1] ?? 0) + 1;
  }
  for (let key = 1; key < cellStart.length; key++) {
    cellStart[key] = (cellStart[key] ?? 0) + (cellStart[key - 1] ?? 0);
  }
  const next = cellStart.slice(0, DUST_GRID * DUST_GRID);
  const positions = new Float32Array(count * 2);
  const slotOf = new Uint32Array(count);
  const order = new Uint32Array(count);
  for (let i = 0; i < count; i++) {
    const key = cell[i] ?? 0;
    const slot = next[key] ?? 0;
    next[key] = slot + 1;
    slotOf[i] = slot;
    order[slot] = i;
    positions[slot * 2] = x[i] ?? 0;
    positions[slot * 2 + 1] = y[i] ?? 0;
  }
  return { positions, slotOf, order, cellStart };
}

/**
 * The runs of the grid's buffer a view needs, as [first, count] pairs: each
 * row of cells the view's Web Mercator box touches, from its first cell in
 * view to its last, empty runs left out.
 */
export function dustRuns(
  cellStart: Uint32Array,
  west: number,
  north: number,
  east: number,
  south: number,
): [first: number, count: number][] {
  const runs: [number, number][] = [];
  const [c0, c1] = [cellOf(west), cellOf(east)];
  for (let row = cellOf(north); row <= cellOf(south); row++) {
    const first = cellStart[row * DUST_GRID + c0] ?? 0;
    const end = cellStart[row * DUST_GRID + c1 + 1] ?? first;
    if (end > first) runs.push([first, end - first]);
  }
  return runs;
}

/**
 * The slots of the grid's schools within `reach` Web Mercator units of
 * (x, y) each way, for a tap on a speck: a few cells' worth, whatever the
 * zoom the dust is drawn at.
 */
export function dustSlotsNear(
  grid: Pick<DustGrid, 'positions' | 'cellStart'>,
  x: number,
  y: number,
  reach: number,
): number[] {
  const slots: number[] = [];
  const [c0, c1] = [cellOf(x - reach), cellOf(x + reach)];
  for (let row = cellOf(y - reach); row <= cellOf(y + reach); row++) {
    const end = grid.cellStart[row * DUST_GRID + c1 + 1] ?? 0;
    for (let slot = grid.cellStart[row * DUST_GRID + c0] ?? end; slot < end; slot++) {
      const dx = (grid.positions[slot * 2] ?? Number.NaN) - x;
      const dy = (grid.positions[slot * 2 + 1] ?? Number.NaN) - y;
      if (Math.abs(dx) <= reach && Math.abs(dy) <= reach) slots.push(slot);
    }
  }
  return slots;
}

/** Attribute locations of the dust program. */
export const DUST_ATTRIB = { position: 0 } as const;

/**
 * Where a speck left out is drawn (a school the glow lights, or of a kind the
 * menu hides): north of the world, never in view.
 */
export const DUST_HIDDEN_Y = -1;

export const DUST_VERT = /* glsl */ `#version 300 es
precision highp float;

layout(location = ${String(DUST_ATTRIB.position)}) in vec2 a_position;

// Mercator (relative to u_origin) to clip space, built in float64 on the CPU.
uniform mat4 u_matrix;
uniform vec2 u_origin;
uniform float u_size;

void main() {
  vec4 clip = u_matrix * vec4(a_position - u_origin, 0.0, 1.0);
  if (clip.w <= 0.0) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 1.0;
    return;
  }
  gl_Position = vec4(clip.xy / clip.w, 0.0, 1.0);
  gl_PointSize = u_size;
}
`;

export const DUST_FRAG = /* glsl */ `#version 300 es
precision highp float;

// Sprite size, the speck's radius and how far past it its edge reaches, device px.
uniform float u_size;
uniform float u_radius;
uniform float u_softness;
// Premultiplied color, its opacity included.
uniform vec4 u_color;

out vec4 fragColor;

void main() {
  float d = length(gl_PointCoord - 0.5) * u_size;
  float cover = 1.0 - smoothstep(u_radius - 1.0, u_radius + u_softness, d);
  if (cover <= 0.0) discard;
  fragColor = u_color * cover;
}
`;

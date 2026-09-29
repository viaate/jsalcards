/**
 * Each school's dot by zoom: how big and how bright it is, from the metro's
 * zoom out to about a whole state, where every school is dust.
 *
 * Two layers draw it, one curve for both, so the eye never sees a handover:
 *
 * - from the first zoom the school tiles hold (schools.ts), MapLibre draws a
 *   dot at each school from them, with its ring and its light;
 * - further out, where the tiles hold nothing, the glow layer draws the same
 *   dot at each school from the directory's own positions (glow-mount.ts,
 *   points.bin), up to SCHOOL_DUST_UNTIL. It draws over the tiles' dots in
 *   the zooms both draw, keeping the brighter of the two at each pixel, so
 *   the same dot drawn twice looks the same as once, and a dot is never
 *   missing where the tiles are still on their way.
 *
 * Zooming out, each dot shrinks and dims a little at every step, like a far
 * marker on a locator bar: never a step where it vanishes or changes look,
 * until it is a faint speck at about a whole state on a laptop, and then
 * gone before the national view, where only the schools lit today glow. The
 * dust stays well under the glow's light at every zoom: a lit school, or a
 * crowd of them, outshines any number of dots, which never add up to more
 * than one (the glow layer keeps the brighter, never the sum).
 */

/** [zoom, value] stops, interpolated linearly as MapLibre does. */
export type DotStops = readonly (readonly [zoom: number, value: number])[];

/** No dust further out than this: the national view, where only statuses glow. */
export const SCHOOL_DUST_FROM = 5;
/**
 * The glow layer's dust ends here, the tiles' dots drawing on alone: a zoom
 * after they start (SCHOOL_TILES_MIN_ZOOM), time enough for the tiles to be
 * in when the map is zoomed in from further out.
 */
export const SCHOOL_DUST_UNTIL = 10;
/**
 * A speck takes taps from this zoom (school-taps.ts): the dust half faded in,
 * as a dot takes them from half drawn (SHOWN_OPACITY there).
 */
export const SCHOOL_DUST_TAPS_FROM = 5.5;
/** Dots whole from this zoom: a metro's whole area on a laptop's screen, and closer. */
export const SCHOOL_DOTS_FROM = 9.5;

/**
 * A dot's radius in CSS pixels: a speck across a state, a point of light
 * across a metro, where a city's schools stand a few pixels apart, a mark
 * beside a name up close.
 */
export const SCHOOL_DOT_RADIUS: DotStops = [
  [SCHOOL_DUST_FROM, 0.6],
  [6, 0.75],
  [7, 0.95],
  [8, 1.25],
  [9, 1.7],
  [10, 2.4],
  [11, 2.7],
  [12, 2.9],
  [13, 3.1],
  [15, 4.5],
  [17, 6],
];

/**
 * A dot's opacity: whole across a metro, dimming as the map zooms out, a
 * faint haze across a state, and none from the national view out.
 */
export const SCHOOL_DOT_OPACITY: DotStops = [
  [SCHOOL_DUST_FROM, 0],
  [6, 0.26],
  [7, 0.38],
  [8, 0.52],
  [9, 0.72],
  [SCHOOL_DOTS_FROM, 1],
];

/**
 * How soft a dot's edge is: 0 edges it as MapLibre edges the tiles' dots,
 * over the pixel inside its radius, from the first zoom the tiles hold (9),
 * where the dust draws over them; 1 eases a pixel further out, so a speck
 * under a pixel across keeps its light and does not twinkle as the map moves.
 */
export const SCHOOL_DOT_SOFTNESS: DotStops = [
  [8, 1],
  [9, 0],
];

/** A curve's value at `zoom`, holding its end values beyond its first and last stops. */
export function dotAt(stops: DotStops, zoom: number): number {
  const first = stops[0];
  if (first === undefined) return 0;
  if (zoom <= first[0]) return first[1];
  for (let i = 1; i < stops.length; i++) {
    const [z0, v0] = stops[i - 1] ?? first;
    const [z1, v1] = stops[i] ?? first;
    if (zoom <= z1) return v0 + ((v1 - v0) * (zoom - z0)) / (z1 - z0);
  }
  return stops[stops.length - 1]?.[1] ?? 0;
}

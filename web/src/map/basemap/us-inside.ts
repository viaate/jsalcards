/**
 * Whether a street tile is wholly inside the US: under one of the US mask's
 * first-zoom tiles that are, listed when the site is built (tools/us-mask.ts).
 * Such a tile is drawn as OpenFreeMap sends it, the mask having nothing to
 * cut from it, so it is asked for without waiting for the mask
 * (street-tiles.ts), and ahead of a flight before the mask is in (index.ts).
 * Most of the country's street tiles are: only those near a border or a
 * coast wait for the mask. Used on the page and in the workers.
 */
import { US_INSIDE_RUNS, US_INSIDE_ZOOM } from 'virtual:snowlight/us-inside';

const inside = new Set<number>();
for (const [y, first, last] of US_INSIDE_RUNS) {
  for (let x = first; x <= last; x++) inside.add(y * 2 ** US_INSIDE_ZOOM + x);
}

/** Whether street tile z/x/y is wholly inside the US, as far as the list says (false if unsure). */
export function insideUs(z: number, x: number, y: number): boolean {
  if (z < US_INSIDE_ZOOM) return false;
  const levels = z - US_INSIDE_ZOOM;
  const ax = Math.floor(x / 2 ** levels);
  const ay = Math.floor(y / 2 ** levels);
  return inside.has(ay * 2 ** US_INSIDE_ZOOM + ax);
}

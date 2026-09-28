/**
 * How many workers parse the bundled lines and, from zoom 7, the street and
 * school tiles: one for each four cores the device has, one or two. Each
 * starts by compiling MapLibre's shared module, and while the map starts they
 * share the cores with the page's main thread: on a phone of four cores, a
 * second one would slow the page more than it speeds the tiles.
 */
export function workerCount(cores: number): number {
  return Number.isFinite(cores) ? Math.min(2, Math.max(1, Math.floor(cores / 4))) : 1;
}

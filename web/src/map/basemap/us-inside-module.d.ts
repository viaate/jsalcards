/** The US mask's first-zoom tiles wholly inside the US (tools/us-mask.ts). */
declare module 'virtual:snowlight/us-inside' {
  /** The zoom of the tiles listed: the mask's first. */
  export const US_INSIDE_ZOOM: number;
  /** The tiles, as runs along each row: [y, first x, last x]. */
  export const US_INSIDE_RUNS: readonly (readonly [number, number, number])[];
}

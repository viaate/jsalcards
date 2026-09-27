/** The data files this build ships (tools/data-files.ts). */
declare module 'virtual:snowlight/data-files' {
  /** Paths under data/, such as "live/closings.json"; empty when no data was staged. */
  export const DATA_FILES: readonly string[];
}

/** The directory's name fixes this build ships (tools/school-names.ts). */
declare module 'virtual:snowlight/school-names' {
  /** A name fix, as src/text/names.ts NameFix: where to stop, the word to end on, the district first. */
  interface ShippedNameFix {
    readonly end?: number;
    readonly word?: string;
    readonly district?: string;
  }
  /** By school id; empty when no directory was staged. */
  export const SCHOOL_NAME_FIXES: Readonly<Record<string, ShippedNameFix>>;
  /** By district id; empty when no directory was staged. */
  export const DISTRICT_NAME_FIXES: Readonly<Record<string, ShippedNameFix>>;
}

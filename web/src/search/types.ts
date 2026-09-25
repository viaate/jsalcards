/**
 * Public types of the search engine: the records the index builder reads,
 * the results a query returns, and the messages between the page and the
 * search worker.
 *
 * This module has no imports, so Node can load it directly from the builder.
 */

/** What a search record describes. */
export type RecordKind = 'school' | 'district' | 'city' | 'zip';

/**
 * One searchable thing, as the index builder reads it (one JSON object per
 * line). `weight` orders matches of equal quality, largest first: enrollment
 * for schools and districts, population for cities.
 */
export interface SearchRecord {
  readonly kind: RecordKind;
  /** Stable identifier: NCES ID, Census GEOID or ZIP code. */
  readonly id: string;
  readonly name: string;
  /** Second line, such as "Lancaster, PA". May be empty. */
  readonly sub: string;
  /** USPS code, such as "PA". */
  readonly state: string;
  readonly lat: number;
  readonly lon: number;
  readonly weight: number;
}

/** Result groups, each ranked on its own. Districts share the schools group. */
export type GroupName = 'schools' | 'cities' | 'zips';

export const GROUP_NAMES: readonly GroupName[] = ['schools', 'cities', 'zips'];

/** The best way every query word matched: whole word, start of a word, or with a typo. */
export type MatchKind = 'exact' | 'prefix' | 'fuzzy';

/** One result. */
export interface SearchHit {
  readonly kind: RecordKind;
  readonly id: string;
  readonly name: string;
  readonly sub: string;
  readonly state: string;
  readonly lat: number;
  readonly lon: number;
  readonly match: MatchKind;
  /** [start, end) UTF-16 ranges of `name` that matched, for bolding. */
  readonly highlight: readonly (readonly [number, number])[];
}

/** What a search resolves to. */
export interface SearchResults {
  /** The query exactly as passed to search(). */
  readonly query: string;
  readonly schools: readonly SearchHit[];
  readonly cities: readonly SearchHit[];
  readonly zips: readonly SearchHit[];
  /**
   * Suggested display order of the groups: ZIPs first for numeric input,
   * otherwise the group with the best top match first.
   */
  readonly order: readonly GroupName[];
}

/** Facts about a loaded index. */
export interface IndexInfo {
  readonly records: number;
  readonly tokens: number;
  /** Compressed bytes fetched. */
  readonly bytes: number;
  /** Milliseconds from the start of the fetch until the worker was ready. */
  readonly loadMs: number;
  /** Where the load time went, in milliseconds. */
  readonly phases: Readonly<Record<string, number>>;
}

/** Page to worker. */
export type WorkerRequest =
  | { readonly type: 'load'; readonly url: string }
  | {
      readonly type: 'query';
      readonly id: number;
      readonly q: string;
      readonly limit: number;
    }
  | { readonly type: 'cancel'; readonly id: number };

/** Worker to page. */
export type WorkerResponse =
  | { readonly type: 'ready'; readonly info: IndexInfo }
  | { readonly type: 'load-error'; readonly message: string }
  | {
      readonly type: 'result';
      readonly id: number;
      readonly results: SearchResults;
      /** Milliseconds the worker spent on this query. */
      readonly ms: number;
    }
  | { readonly type: 'cancelled'; readonly id: number }
  | { readonly type: 'query-error'; readonly id: number; readonly message: string };

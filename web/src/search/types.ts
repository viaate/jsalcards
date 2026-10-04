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
  /**
   * The name as the page shows it, where that has words the written name
   * is not found by ("MIDDLE SCHOOL" of Citizens of the World Charter is
   * shown "Citizens of the World Charter - Middle School"): the record is
   * found by these words as well as its name's. Optional.
   */
  readonly shown?: string;
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
  /** The record's shown name (SearchRecord.shown), when it has one. */
  readonly shown?: string;
  /** [start, end) UTF-16 ranges of `shown` that matched, when it has one. */
  readonly shownHighlight?: readonly (readonly [number, number])[];
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
   * otherwise the group with the best top match first, places ahead of
   * schools when their best matches are as good.
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

/**
 * Where the person is looking: records within `km` of this point rank ahead
 * of the rest, among the ones whose names have every word typed.
 */
export interface NearView {
  readonly lat: number;
  readonly lon: number;
  /** Kilometres from the point that count as near. */
  readonly km: number;
}

/** Page to worker. */
export type WorkerRequest =
  | {
      readonly type: 'load';
      readonly url: string;
      /**
       * The page reads past any service worker (none controls it yet): keep the index in the
       * worker's cache as it downloads (pwa/keep.ts), so the worker never downloads it again.
       */
      readonly keep?: boolean;
    }
  | {
      readonly type: 'query';
      readonly id: number;
      readonly q: string;
      readonly limit: number;
      readonly near?: NearView;
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

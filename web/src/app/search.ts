/**
 * The search bar's side of search: when the index loads, which text is
 * searched, and how results are laid out as options.
 *
 * The index loads on the first focus of the search field, never before. A
 * build that ships no index has no search: the field takes text and shows
 * nothing, and says nothing about why. When the index cannot load, the same.
 * Only the newest text ever shows results.
 */

import type { GroupName, SearchClient, SearchHit, SearchResults } from '../search';
import { casedName, nameLayout, shownRanges } from '../text/names';

/** Makes a search client for an index URL (the client code loads with it). */
export type ClientFactory = (indexUrl: string) => Promise<SearchClient>;

export interface SearchControllerOptions {
  /** The index this build ships, or null when it ships none. */
  readonly indexUrl: string | null;
  /** Called with the newest text's results, or null to show nothing. */
  readonly onResults: (results: SearchResults | null) => void;
  /** Called once the index has loaded (the page can cache it for offline use). */
  readonly onIndexLoaded?: (indexUrl: string) => void;
  readonly createClient?: ClientFactory;
  /** Results per group. Default 5. */
  readonly limit?: number;
}

export interface SearchController {
  /** Starts loading the index, if it has not started. */
  warm(): void;
  /** Searches `text`; an empty text shows nothing. */
  query(text: string): void;
  /** Resolves to the results for `text` once the index is loaded, or null. For links to a ZIP code. */
  lookup(text: string): Promise<SearchResults | null>;
  destroy(): void;
}

const defaultClient: ClientFactory = async (indexUrl) => {
  const { createSearchClient } = await import('../search');
  return createSearchClient(indexUrl);
};

export function createSearchController(options: SearchControllerOptions): SearchController {
  const { indexUrl } = options;
  const createClient = options.createClient ?? defaultClient;
  const limit = options.limit ?? 5;
  let starting: Promise<SearchClient | null> | null = null;
  let client: SearchClient | null = null;
  let unavailable = indexUrl === null;
  let destroyed = false;
  let latest = '';

  const start = (): Promise<SearchClient | null> => {
    if (starting !== null) return starting;
    if (indexUrl === null || destroyed) return Promise.resolve(null);
    starting = createClient(indexUrl).then(
      (made) => {
        if (destroyed) {
          made.destroy();
          return null;
        }
        client = made;
        made.ready.then(
          () => {
            if (!destroyed) options.onIndexLoaded?.(indexUrl);
          },
          () => {
            unavailable = true;
            if (!destroyed && latest.trim() !== '') options.onResults(null);
          },
        );
        return made;
      },
      () => {
        unavailable = true;
        return null;
      },
    );
    return starting;
  };

  const lookup = async (text: string): Promise<SearchResults | null> => {
    if (unavailable || text.trim() === '') return null;
    const made = await start();
    if (made === null || destroyed) return null;
    try {
      return await made.search(text, { limit });
    } catch {
      // Superseded by newer text, or search is unavailable: nothing to show.
      return null;
    }
  };

  return {
    warm() {
      if (!unavailable) void start();
    },
    query(text) {
      latest = text;
      if (text.trim() === '' || unavailable) {
        options.onResults(null);
        return;
      }
      void lookup(text).then((results) => {
        if (destroyed || latest !== text || results === null) return;
        options.onResults(results);
      });
    },
    lookup,
    destroy() {
      destroyed = true;
      client?.destroy();
      client = null;
    },
  };
}

/** One result as the list shows it. */
export interface SearchOption {
  /** Element id, unique within the list. */
  readonly id: string;
  readonly hit: SearchHit;
  /**
   * The hit's name as shown (src/text/names.ts): in title case where it is
   * written in capitals, its shortenings spelled out.
   */
  readonly name: string;
  /** The shown name cut where the text typed matched, for bolding. */
  readonly parts: readonly NamePart[];
  /** The hit's second line as shown, or ''. */
  readonly sub: string;
  readonly group: GroupName;
  /** The first option of a group after the first group. */
  readonly startsGroup: boolean;
}

/**
 * A hit's name as shown, and where the text typed matched it. Schools and
 * districts have their shortenings spelled out; places keep their words.
 */
function shownName(hit: SearchHit): { name: string; highlight: [number, number][] } {
  if (hit.kind === 'city' || hit.kind === 'zip') {
    return { name: casedName(hit.name), highlight: hit.highlight.map(([a, b]) => [a, b]) };
  }
  const layout = nameLayout(hit.name, { state: hit.state });
  return {
    name: layout.map((piece) => piece.text).join(''),
    highlight: shownRanges(layout, hit.name, hit.highlight),
  };
}

/** The results as one list: groups in the suggested order, hits in rank order. */
export function searchOptions(results: SearchResults, idPrefix: string): SearchOption[] {
  const list: SearchOption[] = [];
  for (const group of results.order) {
    results[group].forEach((hit, index) => {
      const shown = shownName(hit);
      list.push({
        id: `${idPrefix}-${String(list.length)}`,
        hit,
        name: shown.name,
        parts: nameParts(shown),
        sub: casedName(hit.sub),
        group,
        startsGroup: index === 0 && list.length > 0,
      });
    });
  }
  return list;
}

/** A name cut into runs that did and did not match, for bolding the matches. */
export interface NamePart {
  readonly text: string;
  readonly match: boolean;
}

/** `hit.name` cut at `hit.highlight`, [start, end) ranges of it. */
export function nameParts(hit: Pick<SearchHit, 'name' | 'highlight'>): NamePart[] {
  const parts: NamePart[] = [];
  const ranges = [...hit.highlight]
    .map(([start, end]) => [Math.max(0, start), Math.min(hit.name.length, end)] as const)
    .filter(([start, end]) => end > start)
    .sort((a, b) => a[0] - b[0]);
  let at = 0;
  for (const [start, end] of ranges) {
    if (end <= at) continue;
    const from = Math.max(start, at);
    if (from > at) parts.push({ text: hit.name.slice(at, from), match: false });
    parts.push({ text: hit.name.slice(from, end), match: true });
    at = end;
  }
  if (at < hit.name.length) parts.push({ text: hit.name.slice(at), match: false });
  return parts;
}

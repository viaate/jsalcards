/**
 * The search bar's side of search: when the index loads, which text is
 * searched, and how results are laid out as options.
 *
 * The index loads on the first focus of the search field, never before. A
 * build that ships no index has no search: the field takes text and shows
 * nothing, and says nothing about why. When the index cannot load, the same.
 * Only the newest text ever shows results.
 */

import { DISTRICT_NAME_FIXES, SCHOOL_NAME_FIXES } from 'virtual:snowlight/school-names';

import type { NearView, RecordKind, SearchClient, SearchHit, SearchResults } from '../search';
import { casedName, nameLayout, shownRanges } from '../text/names';
import type { NameFix } from '../text/names';
import { stateOfId } from '../text/school-names';

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
  /** Results per group. Default SEARCH_LIMIT. */
  readonly limit?: number;
}

export interface SearchController {
  /** Starts loading the index, if it has not started. */
  warm(): void;
  /**
   * Searches `text`; an empty text shows nothing. With `near`, where the
   * person is looking: good matches there come first.
   */
  query(text: string, near?: NearView): void;
  /** Resolves to the results for `text` once the index is loaded, or null. For links to a ZIP code. */
  lookup(text: string, near?: NearView): Promise<SearchResults | null>;
  destroy(): void;
}

const defaultClient: ClientFactory = async (indexUrl) => {
  const { createSearchClient } = await import('../search');
  return createSearchClient(indexUrl);
};

export function createSearchController(options: SearchControllerOptions): SearchController {
  const { indexUrl } = options;
  const createClient = options.createClient ?? defaultClient;
  const limit = options.limit ?? SEARCH_LIMIT;
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

  const lookup = async (text: string, near?: NearView): Promise<SearchResults | null> => {
    if (unavailable || text.trim() === '') return null;
    const made = await start();
    if (made === null || destroyed) return null;
    try {
      return await made.search(text, near === undefined ? { limit } : { limit, near });
    } catch {
      // Superseded by newer text, or search is unavailable: nothing to show.
      return null;
    }
  };

  return {
    warm() {
      if (!unavailable) void start();
    },
    query(text, near) {
      latest = text;
      if (text.trim() === '' || unavailable) {
        options.onResults(null);
        return;
      }
      void lookup(text, near).then((results) => {
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

/**
 * Where the person is looking, for search to put good matches there first:
 * from zoom NEAR_FROM_ZOOM in, a view's middle and the distance to its
 * corners, kept between NEAR_MIN_KM (a town's schools) and NEAR_MAX_KM (a
 * region's). Further out the view is the country, or most of it, and no
 * place is nearer than another.
 */
export const NEAR_FROM_ZOOM = 6;
export const NEAR_MIN_KM = 40;
export const NEAR_MAX_KM = 250;
/** The Earth's circumference at the equator, in metres, and MapLibre's tile size in CSS pixels. */
const EARTH_METRES = 40_075_016.686;
const TILE_PIXELS = 512;

/** The near view of a map view on a screen `width` by `height` CSS pixels, or undefined. */
export function nearView(
  view: { readonly lat: number; readonly lon: number; readonly zoom: number },
  width: number,
  height: number,
): NearView | undefined {
  if (!(view.zoom >= NEAR_FROM_ZOOM)) return undefined;
  const metresPerPixel =
    (EARTH_METRES * Math.cos((view.lat * Math.PI) / 180)) / (TILE_PIXELS * 2 ** view.zoom);
  const km = (Math.hypot(width, height) / 2) * (metresPerPixel / 1000);
  return {
    lat: view.lat,
    lon: view.lon,
    km: Math.min(NEAR_MAX_KM, Math.max(NEAR_MIN_KM, km)),
  };
}

/**
 * Results asked of each group: enough for a full section of districts and
 * one of schools, which rank together, and for the rows lost to repeats.
 */
export const SEARCH_LIMIT = 16;

/** Rows the list shows at most, unless every section's first rows need more. */
export const LIST_ROWS = 12;
/** Rows every section with results shows, when it has them. */
const SECTION_FLOOR = 2;
/** Rows each section shows before any section takes the rows others leave. */
const SECTION_ROWS: Readonly<Record<RecordKind, number>> = {
  city: 4,
  district: 3,
  school: 5,
  zip: 5,
};
/** Rows one section shows at most. */
const SECTION_MAX = 8;
/** Degrees apart, north to south and east to west, within which two records are one place. */
const SAME_PLACE = 0.01;

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
  /** The section it is listed in: one kind of result each. */
  readonly section: RecordKind;
}

/** One kind of result, as the list shows it under its heading. */
export interface SearchSection {
  readonly kind: RecordKind;
  readonly options: readonly SearchOption[];
  /** Its first option's place in the whole list. */
  readonly start: number;
}

/** The directory's fixes for the names of schools and of districts (tools/school-names.ts). */
export interface NameFixTables {
  readonly schools: Readonly<Record<string, NameFix>>;
  readonly districts: Readonly<Record<string, NameFix>>;
}

const BUILD_FIXES: NameFixTables = { schools: SCHOOL_NAME_FIXES, districts: DISTRICT_NAME_FIXES };

/**
 * A hit's name as shown, and where the text typed matched it. Schools and
 * districts read as the map names them (school-tiles.ts), by the state their
 * id says: their shortenings spelled out, and the directory's fix for their
 * name applied (a name NCES cut off, or a school named only "Elementary
 * School" named with its district first). Places keep their words.
 *
 * Where the shown name has words the written one is not found by, the index
 * has it too (SearchHit.shown), and the match is marked in it as it is.
 */
function shownName(
  hit: SearchHit,
  fixes: NameFixTables,
): { name: string; highlight: [number, number][] } {
  if (hit.kind === 'city' || hit.kind === 'zip') {
    return { name: casedName(hit.name), highlight: hit.highlight.map(([a, b]) => [a, b]) };
  }
  const fix = (hit.kind === 'school' ? fixes.schools : fixes.districts)[hit.id] ?? {};
  const hint = { state: stateOfId(hit.id), district: hit.kind === 'district' };
  const layout = nameLayout(hit.name, hint, fix);
  const name = layout.map((piece) => piece.text).join('');
  if (
    hit.shown !== undefined &&
    hit.shownHighlight !== undefined &&
    hit.shown === name.replace(/\s{2,}/gu, ' ').trim()
  ) {
    return { name: hit.shown, highlight: hit.shownHighlight.map(([a, b]) => [a, b]) };
  }
  return { name, highlight: shownRanges(layout, hit.name, hit.highlight) };
}

interface Shown {
  readonly hit: SearchHit;
  readonly name: string;
  readonly highlight: [number, number][];
  readonly sub: string;
}

/**
 * Whether two rows would read the same and are one place: the directory lists
 * a few private schools twice, under two ids, at one address. Schools of one
 * name in one town that stand apart both stay.
 */
function sameRow(a: Shown, b: Shown): boolean {
  return (
    a.hit.kind === b.hit.kind &&
    a.name === b.name &&
    a.sub === b.sub &&
    Math.abs(a.hit.lat - b.hit.lat) < SAME_PLACE &&
    Math.abs(a.hit.lon - b.hit.lon) < SAME_PLACE
  );
}

/**
 * Rows for each section, in list order: every section its first
 * SECTION_FLOOR, then each in turn up to its SECTION_ROWS, then each in turn
 * up to SECTION_MAX, while the list has room.
 */
function shareRows(sections: readonly { kind: RecordKind; size: number }[]): number[] {
  const rows = sections.map(({ size }) => Math.min(size, SECTION_FLOOR));
  let room = LIST_ROWS - rows.reduce((sum, n) => sum + n, 0);
  for (const cap of [(kind: RecordKind) => SECTION_ROWS[kind], () => SECTION_MAX]) {
    sections.forEach(({ kind, size }, i) => {
      const more = Math.min(room, Math.min(size, cap(kind)) - (rows[i] ?? 0));
      if (more <= 0) return;
      rows[i] = (rows[i] ?? 0) + more;
      room -= more;
    });
  }
  return rows;
}

/**
 * The results as one list of sections, one kind of result each: places,
 * ZIP codes, districts and schools. Sections come in the suggested group
 * order; districts and schools, which rank as one group, come in the order
 * of their best hit. Hits keep their rank order, a row that repeats one
 * above it is left out, and the list shows at most LIST_ROWS rows.
 */
export function searchOptions(
  results: SearchResults,
  idPrefix: string,
  fixes: NameFixTables = BUILD_FIXES,
): SearchOption[] {
  const sections: { kind: RecordKind; rows: Shown[] }[] = [];
  for (const group of results.order) {
    for (const hit of results[group]) {
      const shown: Shown = { hit, ...shownName(hit, fixes), sub: casedName(hit.sub) };
      let section = sections.find((s) => s.kind === hit.kind);
      if (section === undefined) {
        section = { kind: hit.kind, rows: [] };
        sections.push(section);
      }
      if (!section.rows.some((row) => sameRow(row, shown))) section.rows.push(shown);
    }
  }
  const counts = shareRows(sections.map(({ kind, rows }) => ({ kind, size: rows.length })));
  const list: SearchOption[] = [];
  sections.forEach(({ kind, rows }, s) => {
    for (const row of rows.slice(0, counts[s] ?? 0)) {
      list.push({
        id: `${idPrefix}-${String(list.length)}`,
        hit: row.hit,
        name: row.name,
        parts: nameParts(row),
        sub: row.sub,
        section: kind,
      });
    }
  });
  return list;
}

/** A list's options under their sections, in list order. */
export function searchSections(options: readonly SearchOption[]): SearchSection[] {
  const sections: { kind: RecordKind; options: SearchOption[]; start: number }[] = [];
  options.forEach((option, index) => {
    const last = sections[sections.length - 1];
    if (last?.kind === option.section) last.options.push(option);
    else sections.push({ kind: option.section, options: [option], start: index });
  });
  return sections;
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

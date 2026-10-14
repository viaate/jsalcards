/**
 * Runs queries against a loaded index.
 *
 * Each group (schools with districts, cities, ZIP codes) is ranked on its
 * own. A record's level is the best of:
 *
 *   0  exact name: every word matches a whole word and together they are the
 *      whole name ("lancaster" for the city Lancaster), or the whole name
 *      as the page shows it (a record's shown name, types.ts SearchRecord)
 *   then for each tier (exact, then prefix, then typo):
 *      all words in the name / some in the name, rest in the place / all in
 *      the place ("lancaster" for a school in Lancaster, PA)
 *   last  the query is only a state name
 *
 * and inside a level records come heaviest first, ties in index order, so the
 * output is stable. On levels where every word is in the name, judged over
 * the level's heaviest PHRASE_WINDOW records:
 *
 * - with two or more words, names holding them side by side in the order
 *   typed come first ("ps 12" puts "PS 12 Lewis and Clark" ahead of "Public
 *   Schools ... K-12"; see phrase.ts);
 * - among those, a name that starts with the words, a leading "The" aside,
 *   goes ahead of one that does not unless that one is START_FACTOR times
 *   heavier ("pembroke" puts "The Pembroke Hill School" ahead of "Franklin
 *   Academy Pembroke Pines", and "lancaster pa" keeps the School District of
 *   Lancaster ahead of Lancaster Mennonite School).
 *
 * Sets are bitsets over each group's weight ranks: filling
 * one from a dictionary range is a single run over contiguous postings, and a
 * level is a few AND/OR passes, so the first `limit` set bits of each level
 * in rank order are the answer. Typo matching only runs when the exact and
 * prefix levels leave a group short.
 *
 * One exception to level order: a name that starts with the words typed, as
 * whole words, goes ahead of an exact name it outweighs LEAD_FACTOR times
 * over. "kansas" lists Kansas City, MO and Kansas City, KS ahead of the
 * villages named Kansas, which still follow; "portland" keeps Portland,
 * Tennessee ahead of South Portland, which does not start with the word.
 */
import type { GroupData, RecordView, SearchIndex } from './decode';
import {
  canonicalLength,
  isNumericToken,
  queryExpansions,
  ruleHolds,
  rulesStartingWith,
  tokenize,
  typoBudget,
} from './normalize';
import { isPhrase } from './phrase';
import { Tier, parseQuery } from './query';
import type { ParsedQuery, Reading, TierValue } from './query';
import { STATES } from './states';
import { prefixDistance } from './trie';
import { GROUP_NAMES } from './types';
import type { GroupName, MatchKind, NearView, SearchHit, SearchResults } from './types';

export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 50;
/** Whole words this common are taken as spelled right: no typo matching for them. */
export const TYPO_RARE = 3;
/** Records per level, heaviest first, checked for phrase order. */
export const PHRASE_WINDOW = 64;
/** Where a name has the words typed, best first (SearchEngine.wordsPlace). */
const WORDS_START = 0;
const WORDS_TOGETHER = 1;
const WORDS_APART = 2;
/** A word a name may start with before the words typed. */
const LEADING_ARTICLE = 'the';
/** How many times heavier a name must be to go ahead of one starting with the words. */
export const START_FACTOR = 4;
/** START_FACTOR in weight codes. */
const START_CODES = Math.round(Math.log2(START_FACTOR) * 128);
/** How many times heavier a name starting with the words must be to lead an exact name. */
export const LEAD_FACTOR = 20;
/** LEAD_FACTOR in weight codes (format.ts quantizeWeight: 128 per doubling). */
const LEAD_CODES = Math.round(Math.log2(LEAD_FACTOR) * 128);

const CITIES = 1;
/**
 * Group order between groups whose best matches are equally good, by group
 * index: places, then schools, then ZIP codes. A place named exactly as typed
 * is the broadest reading of the text ("kansas city" is the city before it is
 * the district of that name), and the place's schools are one step away.
 */
const TIE_RANK: readonly number[] = [1, 0, 2];
const FULL = 0;
/** Every word a whole word of the name, not the whole name: where leading names come from. */
const IN_NAME = 1;
const STATE_ONLY = 10;
const LEVEL_COUNT = 11;
/** Where a level's words may match; the third field, 2, is anywhere. */
const ALL_IN_NAME = 0;
const SOME_IN_NAME = 1;

function levelTier(level: number): TierValue {
  if (level === FULL) return Tier.exact;
  return Math.min(2, Math.floor((level - 1) / 3)) as TierValue;
}

function levelField(level: number): number {
  return (level - 1) % 3;
}

const MATCH_KIND: readonly MatchKind[] = ['exact', 'prefix', 'fuzzy'];

/** Zeroed bitsets of one size, handed out per query and all returned after it. */
class BitPool {
  private readonly free: Uint32Array[] = [];
  private readonly used: Uint32Array[] = [];
  readonly words: number;

  constructor(words: number) {
    this.words = words;
  }

  take(): Uint32Array {
    const bits = this.free.pop() ?? new Uint32Array(this.words);
    this.used.push(bits);
    return bits;
  }

  copy(from: Uint32Array): Uint32Array {
    const bits = this.take();
    bits.set(from);
    return bits;
  }

  releaseAll(): void {
    for (const bits of this.used) {
      bits.fill(0);
      this.free.push(bits);
    }
    this.used.length = 0;
  }
}

const EMPTY_RANGES: readonly number[] = [];

/** One distinct query word and what it matches in the dictionary. */
class Word {
  readonly text: string;
  readonly budget: number;
  readonly exact: number;
  readonly prefixLo: number;
  readonly prefixHi: number;
  /** Token ids of each abbreviation expansion whose words are all indexed. */
  readonly expansions: readonly (readonly number[])[];
  private fuzzyRanges: readonly number[] | null = null;
  /** Per group, per field (0 name, 1 anywhere), per tier. */
  readonly cache: (Uint32Array | null)[];

  constructor(text: string, index: SearchIndex) {
    this.text = text;
    this.budget = typoBudget(text);
    const trie = index.trie;
    this.exact = trie.exact(text);
    [this.prefixLo, this.prefixHi] = trie.prefix(text);
    const expansions: number[][] = [];
    for (const words of queryExpansions(text)) {
      const ids = words.map((w) => trie.exact(w));
      if (ids.every((id) => id >= 0)) expansions.push(ids);
    }
    this.expansions = expansions;
    this.cache = new Array<Uint32Array | null>(index.groups.length * 6).fill(null);
  }

  /** Records (and places) that have exactly this word, across groups. */
  private known(index: SearchIndex): number {
    const t = this.exact;
    if (t < 0) return 0;
    let n = (index.locOff[t + 1] ?? 0) - (index.locOff[t] ?? 0);
    for (const group of index.groups) n += (group.nameOff[t + 1] ?? 0) - (group.nameOff[t] ?? 0);
    return n;
  }

  /** Postings under this word's prefix in a group: a cheap guess at how common it is. */
  spread(group: GroupData): number {
    return (group.nameOff[this.prefixHi] ?? 0) - (group.nameOff[this.prefixLo] ?? 0);
  }

  /**
   * Token ranges within the typo budget, unless the word is a common word in
   * its own right: when TYPO_RARE or more records have exactly this token, it
   * is spelled as meant and typo matches would only be noise ("portland"
   * should not find Orlando). A word that only starts common tokens, like
   * "hight" or a half-typed "lancas", keeps its typo matches.
   */
  fuzzy(index: SearchIndex): readonly number[] {
    if (this.fuzzyRanges === null) {
      if (this.budget === 0 || this.known(index) >= TYPO_RARE) {
        this.fuzzyRanges = EMPTY_RANGES;
      } else {
        const out: number[] = [];
        index.trie.fuzzy(this.text, this.budget, out);
        this.fuzzyRanges = out;
      }
    }
    return this.fuzzyRanges;
  }
}

function setPostings(
  bits: Uint32Array,
  off: Uint32Array,
  post: Uint32Array,
  lo: number,
  hi: number,
): void {
  if (hi <= lo) return;
  const stop = off[hi] ?? 0;
  for (let p = off[lo] ?? 0; p < stop; p++) {
    const r = post[p] ?? 0;
    bits[r >>> 5] = (bits[r >>> 5] ?? 0) | (1 << (r & 31));
  }
}

function setPlaces(
  bits: Uint32Array,
  index: SearchIndex,
  group: GroupData,
  lo: number,
  hi: number,
): void {
  const { subOff, subRanks } = group;
  if (hi <= lo || !subOff || !subRanks) return;
  const { locOff, locSubs } = index;
  const stop = locOff[hi] ?? 0;
  for (let p = locOff[lo] ?? 0; p < stop; p++) {
    const s = locSubs[p] ?? 0;
    const end = subOff[s + 1] ?? 0;
    for (let q = subOff[s] ?? 0; q < end; q++) {
      const r = subRanks[q] ?? 0;
      bits[r >>> 5] = (bits[r >>> 5] ?? 0) | (1 << (r & 31));
    }
  }
}

function andInto(target: Uint32Array, other: Uint32Array): void {
  for (let w = 0; w < target.length; w++) target[w] = (target[w] ?? 0) & (other[w] ?? 0);
}

function orInto(target: Uint32Array, other: Uint32Array): void {
  for (let w = 0; w < target.length; w++) target[w] = (target[w] ?? 0) | (other[w] ?? 0);
}

function isEmpty(bits: Uint32Array): boolean {
  for (const word of bits) if (word !== 0) return false;
  return true;
}

/** State membership bitsets, built on first use and kept. */
class StateMasks {
  private readonly masks = new Map<number, Uint32Array>();

  get(group: GroupData, g: number, state: number): Uint32Array {
    const key = g * 64 + state;
    let mask = this.masks.get(key);
    if (!mask) {
      mask = new Uint32Array(group.words);
      const ks = group.kindState;
      for (let r = 0; r < group.size; r++) {
        if (((ks[r] ?? 0) & 63) === state) mask[r >>> 5] = (mask[r >>> 5] ?? 0) | (1 << (r & 31));
      }
      this.masks.set(key, mask);
    }
    return mask;
  }
}

interface Found {
  readonly rank: number;
  readonly level: number;
  /** Near where the person is looking (NearView). */
  readonly near?: boolean;
}

/**
 * Levels on which a record near where the person is looking goes first: the
 * exact name, and every word typed in the name, whole or as its start. A
 * record matched only through its place, or through a typo, keeps its level.
 */
const NEAR_LEVELS: readonly number[] = [FULL, IN_NAME, IN_NAME + 3];
/** Kilometres in a degree of latitude, and of longitude at the equator. */
const KM_PER_DEGREE = 111.2;

/** Whether a point is within `near.km` of `near`: flat-earth distance, fine at a region's scale. */
function isNear(near: NearView, lat: number, lon: number): boolean {
  const dy = (lat - near.lat) * KM_PER_DEGREE;
  const dx = (lon - near.lon) * KM_PER_DEGREE * Math.cos((near.lat * Math.PI) / 180);
  return dx * dx + dy * dy <= near.km * near.km;
}

/** Kilometres around a town a query ends with that count as that town (a metro area). */
export const TOWN_KM = 40;
/** Most words of a town's name read from the end of a query. */
const TOWN_WORDS = 3;
/** Towns of that name tried, most populous first (Kansas City, MO and KS). */
const TOWN_CHOICES = 3;
/** Words that join a name to the town after it. */
const TOWN_JOINERS = new Set(['in', 'near', 'at']);
const TOWN_ORDER: readonly GroupName[] = ['schools', 'cities', 'zips'];
const ZIP_ORDER: readonly GroupName[] = ['schools', 'zips', 'cities'];
const CITY_GROUP = GROUP_NAMES.indexOf('cities');
const ZIP_GROUP = GROUP_NAMES.indexOf('zips');
/** A ZIP code as a word. */
const ZIP_WORD = /^\d{5}$/u;
/** A state's code or whole name, as tokens joined by spaces, to its code. */
const STATE_WORDS: ReadonlyMap<string, string> = new Map(
  STATES.flatMap(([code, name]) => [
    [code.toLowerCase(), code],
    [tokenize(name).join(' '), code],
  ]),
);
/** Longest state name, in words ("district of columbia"). */
const STATE_WORDS_MAX = 3;

/** Town readings remembered, by the town words they were read for. */
const TOWN_CACHE = 64;

/** A way to read a query: as typed, or as a name near a town or ZIP code it ends with. */
interface TownReading {
  readonly query: string;
  readonly view: NearView | undefined;
  readonly town?: SearchHit;
  /** Whether this reading only asks if the name finds any school at all. */
  readonly probe?: boolean;
}

export class SearchEngine {
  readonly index: SearchIndex;
  private readonly pools: readonly BitPool[];
  private readonly states = new StateMasks();
  private readonly towns = new Map<string, RecordView[]>();

  constructor(index: SearchIndex) {
    this.index = index;
    this.pools = index.groups.map((g) => new BitPool(g.words));
  }

  /**
   * With `near`, the records within its distance whose names have every word
   * typed (NEAR_LEVELS) come first in their group, best level first, and a
   * group with such records comes before the groups without.
   *
   * A query that finds no school and no place it names (namesPlace) but ends
   * with a town's name ("st annes catholic school kansas city", "in" or "near"
   * before the town aside) is read as a name and that town: the schools within
   * TOWN_KM of the town whose names have the other words, the town listed first
   * among the places the query found. A school in a suburb is found by the city
   * people name it by, and a town typed in full ("old mystic") stays that town.
   */
  search(raw: string, limit = DEFAULT_LIMIT, near?: NearView): SearchResults {
    // One call site for every reading keeps the copy lint's walk of this file short.
    const readings: TownReading[] = [{ query: raw, view: near }];
    let first: SearchResults | null = null;
    const noSchool = new Set<string>();
    for (const reading of readings) {
      // A name no school has anywhere has none near any town: its towns are skipped.
      if (reading.town !== undefined && noSchool.has(reading.query)) continue;
      const results = this.searchOnce(reading.query, limit, reading.view);
      if (reading.probe) {
        if (results.schools.length === 0) noSchool.add(reading.query);
        continue;
      }
      const { town, view } = reading;
      if (town === undefined || view === undefined) {
        if (results.schools.length > 0 || parseQuery(raw).numeric || this.namesPlace(raw)) {
          return results;
        }
        first = results;
        readings.push(...this.townReadings(raw));
        continue;
      }
      const schools = results.schools.filter((h) => isNear(view, h.lat, h.lon));
      if (schools.length > 0) {
        // The town (or ZIP code) listed first among the places the query found.
        const zip = town.kind === 'zip';
        const found = (zip ? first?.zips : first?.cities) ?? [];
        const cap = Math.max(1, Math.min(MAX_LIMIT, Math.floor(limit) || DEFAULT_LIMIT));
        const places = [town, ...found.filter((c) => c.id !== town.id)].slice(0, cap);
        const cities = zip ? (first?.cities ?? []) : places;
        const zips = zip ? places : (first?.zips ?? []);
        return { query: raw, schools, cities, zips, order: zip ? ZIP_ORDER : TOWN_ORDER };
      }
    }
    return first ?? this.searchOnce(raw, limit, near);
  }

  /**
   * Whether the query is a place's name, or the start of one with its last word
   * still being typed ("old mystic", "ben avo"), with or without its state after
   * it ("old mystic ct"). A town the query names is what it means, so no other
   * town is read into it.
   */
  private namesPlace(raw: string): boolean {
    const words = tokenize(raw);
    const n = words.length;
    if (n > 1 && this.townsNamed(words, true).length > 0) return true;
    for (let k = Math.min(STATE_WORDS_MAX, n - 2); k >= 1; k--) {
      const state = STATE_WORDS.get(words.slice(n - k).join(' '));
      if (state !== undefined && this.townsNamed(words.slice(0, n - k), true, state).length > 0) {
        return true;
      }
    }
    return false;
  }

  /**
   * A query read as a name and the place it ends with: a ZIP code ("st ann
   * 66208"), or a town, for each town of that name. A state after the town
   * ("kansas city ks", "kansas city, kansas") is not part of the name and
   * chooses between towns of that name; the town is also read without it.
   */
  private townReadings(raw: string): TownReading[] {
    const spans: number[][] = [];
    const tokens = tokenize(raw, spans);
    const out: TownReading[] = [];
    const n = tokens.length;
    if (n > 1 && ZIP_WORD.test(tokens[n - 1] ?? '')) {
      this.placeReadings(raw, tokens, spans, n, 1, undefined, out);
    }
    for (let k = Math.min(STATE_WORDS_MAX, n - 2); k >= 1; k--) {
      const state = STATE_WORDS.get(tokens.slice(n - k).join(' '));
      if (state === undefined) continue;
      for (let t = Math.min(TOWN_WORDS, n - k - 1); t >= 1; t--) {
        this.placeReadings(raw, tokens, spans, n - k, t, state, out);
      }
    }
    for (let t = Math.min(TOWN_WORDS, n - 1); t >= 1; t--) {
      this.placeReadings(raw, tokens, spans, n, t, undefined, out);
    }
    return out;
  }

  /**
   * Readings of the first `end` tokens as a name and the `k` words before `end`
   * as a place (a ZIP code when they are one, else a town, in `state` if given).
   */
  private placeReadings(
    raw: string,
    tokens: readonly string[],
    spans: readonly number[][],
    end: number,
    k: number,
    state: string | undefined,
    out: TownReading[],
  ): void {
    // The name is the query as typed up to the place (or a joining word before it).
    let stop = end - k;
    while (stop > 1 && TOWN_JOINERS.has(tokens[stop - 1] ?? '')) stop--;
    const query = raw.slice(0, spans[stop]?.[0] ?? raw.length);
    const words = tokens.slice(end - k, end);
    const zip = k === 1 && ZIP_WORD.test(words[0] ?? '');
    const places = this.townsNamed(words, false, state, zip ? ZIP_GROUP : CITY_GROUP);
    if (places.length > 0) out.push({ query, view: undefined, probe: true });
    for (const place of places) {
      out.push({
        query,
        view: { lat: place.lat, lon: place.lon, km: TOWN_KM },
        town: { ...place, match: 'exact', highlight: [[0, place.name.length]] },
      });
    }
  }

  /**
   * The towns whose whole name is `words`, most populous first, at most
   * TOWN_CHOICES; with `typing`, the towns whose names start with `words`, the
   * last perhaps cut short. Only names of that many words (or more, typing),
   * abbreviations spelled out, are read from the index (GroupData.canon), and
   * each answer is remembered. With `state`, only towns in that state; with
   * `g` the ZIP group, the ZIP codes of that name.
   */
  private townsNamed(
    words: readonly string[],
    typing = false,
    state?: string,
    g = CITY_GROUP,
  ): RecordView[] {
    const key = `${String(g)}${state ?? ''}${typing ? '>' : '='}${words.join(' ')}`;
    const known = this.towns.get(key);
    if (known) return known;
    const group = this.index.groups[g];
    const first = this.index.trie.exact(words[0] ?? '');
    const last = words.length - 1;
    const out: RecordView[] = [];
    if (group && first >= 0) {
      const end = group.nameOff[first + 1] ?? 0;
      const count = canonicalLength(typing ? words.slice(0, last) : words) + (typing ? 1 : 0);
      const ranks: number[] = [];
      for (let i = group.nameOff[first] ?? 0; i < end; i++) {
        const rank = group.namePost[i] ?? 0;
        const canon = group.canon[rank] ?? 0;
        if (canon === count || (typing && canon > count)) ranks.push(rank);
      }
      for (const rank of ranks.sort((a, b) => a - b)) {
        const rec = this.index.record(group.fileIndex[rank] ?? 0);
        const name = tokenize(rec.name);
        const fits = typing ? name.length >= words.length : name.length === words.length;
        const same = words.every(
          (w, i) => name[i] === w || (typing && i === last && name[i]?.startsWith(w)),
        );
        if (fits && same && (state === undefined || rec.state === state)) out.push(rec);
        if (out.length === TOWN_CHOICES) break;
      }
    }
    if (this.towns.size >= TOWN_CACHE) this.towns.clear();
    this.towns.set(key, out);
    return out;
  }

  private searchOnce(raw: string, limit = DEFAULT_LIMIT, near?: NearView): SearchResults {
    const cap = Math.max(1, Math.min(MAX_LIMIT, Math.floor(limit) || DEFAULT_LIMIT));
    const parsed = parseQuery(raw);
    const empty: SearchResults = {
      query: raw,
      schools: [],
      cities: [],
      zips: [],
      order: parsed.numeric ? ['zips', 'schools', 'cities'] : GROUP_NAMES,
    };
    if (parsed.readings.length === 0) return empty;

    const words = parsed.words.map((w) => new Word(w, this.index));
    const found: Found[][] = [];
    try {
      for (let g = 0; g < this.index.groups.length; g++) {
        found.push(this.searchGroup(g, parsed, words, cap, near));
      }
    } finally {
      for (const pool of this.pools) pool.releaseAll();
    }

    const hits = found.map((list, g) => list.map((f) => this.hit(g, f, words)));
    const [schools = [], cities = [], zips = []] = hits;
    let order: readonly GroupName[];
    if (parsed.numeric) {
      order = ['zips', 'schools', 'cities'];
    } else {
      // A leading name can come before its group's exact names: the group's best is its lowest level.
      const best = (g: number): number =>
        (found[g] ?? []).reduce((low, f) => Math.min(low, f.level), LEVEL_COUNT);
      // A group with records near where the person is looking comes first.
      const far = (g: number): number => ((found[g] ?? []).some((f) => f.near === true) ? 0 : 1);
      order = [0, 1, 2]
        .sort(
          (a, b) => far(a) - far(b) || best(a) - best(b) || (TIE_RANK[a] ?? a) - (TIE_RANK[b] ?? b),
        )
        .map((g) => GROUP_NAMES[g] ?? 'schools');
    }
    return { query: raw, schools, cities, zips, order };
  }

  private hit(g: number, f: Found, words: readonly Word[]): SearchHit {
    const group = this.index.groups[g];
    const rec = this.index.record(group?.fileIndex[f.rank] ?? 0);
    const tier = f.level === STATE_ONLY ? Tier.exact : levelTier(f.level);
    const hit: SearchHit = {
      ...rec,
      match: MATCH_KIND[tier] ?? 'exact',
      highlight: highlight(rec.name, words, tier),
    };
    return rec.shown === undefined
      ? hit
      : { ...hit, shownHighlight: highlight(rec.shown, words, tier) };
  }

  /**
   * A group's records near `near` on NEAR_LEVELS, best level first, heaviest
   * first within a level; at most `cap`.
   */
  private nearGroup(
    g: number,
    group: GroupData,
    pool: BitPool,
    parsed: ParsedQuery,
    words: readonly Word[],
    cap: number,
    near: NearView,
  ): Found[] {
    const out: Found[] = [];
    const seen = new Set<number>();
    for (const level of NEAR_LEVELS) {
      const bits = this.levelBits(level, g, group, pool, parsed.readings, words);
      if (!bits) continue;
      for (let w = 0; w < bits.length && out.length < cap; w++) {
        let x = bits[w] ?? 0;
        while (x !== 0 && out.length < cap) {
          const low = x & -x;
          const rank = w * 32 + 31 - Math.clz32(low);
          x ^= low;
          if (seen.has(rank)) continue;
          const file = group.fileIndex[rank] ?? 0;
          if (!isNear(near, this.index.lat(file), this.index.lon(file))) continue;
          seen.add(rank);
          out.push({ rank, level, near: true });
        }
      }
    }
    return out;
  }

  private searchGroup(
    g: number,
    parsed: ParsedQuery,
    words: readonly Word[],
    cap: number,
    near?: NearView,
  ): Found[] {
    const group = this.index.groups[g];
    const pool = this.pools[g];
    if (!group || !pool || group.size === 0) return [];
    const nearby =
      near === undefined ? [] : this.nearGroup(g, group, pool, parsed, words, cap, near);
    const placed = new Set(nearby.map((f) => f.rank));
    let out: Found[] = [];
    const taken = (rank: number): boolean => placed.has(rank) || out.some((f) => f.rank === rank);

    for (let level = 0; level < LEVEL_COUNT; level++) {
      // After exact names, the next level is read even when they fill the
      // list: a far heavier name starting with the words goes ahead of them.
      const leading = level === IN_NAME && out.length > 0;
      if (out.length >= cap && !leading) break;
      const bits = this.levelBits(level, g, group, pool, parsed.readings, words);
      if (!bits) continue;
      const room = leading ? cap : cap - out.length;
      const ordered = this.orderReadings(level, parsed.readings);
      // Without an order to judge, take records straight off the set; with
      // one, take the level's heaviest few and put the best placed first.
      const want = ordered ? Math.max(PHRASE_WINDOW, room) : room;
      const ranks: number[] = [];
      for (let w = 0; w < bits.length && ranks.length < want; w++) {
        let x = bits[w] ?? 0;
        while (x !== 0 && ranks.length < want) {
          const low = x & -x;
          const rank = w * 32 + 31 - Math.clz32(low);
          x ^= low;
          if (!taken(rank)) ranks.push(rank);
        }
      }
      const next: Found[] = [];
      if (ordered) {
        const tier = level === FULL ? Tier.exact : levelTier(level);
        const starting: number[] = [];
        const together: number[] = [];
        const apart: number[] = [];
        for (const rank of ranks) {
          const place = this.wordsPlace(group, rank, ordered, words, tier);
          if (place === WORDS_START) starting.push(rank);
          else if (place === WORDS_TOGETHER) together.push(rank);
          else apart.push(rank);
        }
        for (const rank of [...this.startFirst(group, starting, together), ...apart]) {
          if (next.length < room) next.push({ rank, level });
        }
      } else {
        for (const rank of ranks) next.push({ rank, level });
      }
      out = leading
        ? this.lead(group, out, next, parsed.readings, words).slice(0, cap)
        : out.concat(next);
    }
    return nearby.length === 0 ? out : [...nearby, ...out].slice(0, cap);
  }

  /**
   * Exact names and the next level's records in one order: exact names
   * first, except that a record whose name starts with the words typed goes
   * ahead of each exact name it outweighs LEAD_FACTOR times over. Both
   * lists keep their own order.
   */
  private lead(
    group: GroupData,
    exact: readonly Found[],
    next: readonly Found[],
    readings: readonly Reading[],
    words: readonly Word[],
  ): Found[] {
    const usable = readings.filter((r) => r.words.length > 0 && Tier.exact >= r.floor);
    const weight = (f: Found): number => group.weight[f.rank] ?? 0;
    const lightest = exact.reduce((low, f) => Math.min(low, weight(f)), Number.POSITIVE_INFINITY);
    const leaders = next.filter(
      (f) =>
        weight(f) - lightest >= LEAD_CODES &&
        this.inPhrase(group, f.rank, usable, words, Tier.exact, true),
    );
    if (leaders.length === 0) return [...exact, ...next];
    const merged: Found[] = [];
    let i = 0;
    let j = 0;
    while (i < exact.length) {
      const leader = leaders[j];
      const name = exact[i];
      if (leader && name && weight(leader) - weight(name) >= LEAD_CODES) {
        merged.push(leader);
        j++;
      } else if (name) {
        merged.push(name);
        i++;
      }
    }
    const placed = new Set(merged.map((f) => f.rank));
    return merged.concat(next.filter((f) => !placed.has(f.rank)));
  }

  /**
   * Names starting with the words and the rest, heaviest first each, in one
   * order: a name starting with the words goes first unless the other is
   * START_FACTOR times heavier or more.
   */
  private startFirst(
    group: GroupData,
    starting: readonly number[],
    rest: readonly number[],
  ): number[] {
    const weight = (rank: number): number => group.weight[rank] ?? 0;
    const merged: number[] = [];
    let i = 0;
    let j = 0;
    while (i < starting.length || j < rest.length) {
      const start = starting[i];
      const other = rest[j];
      if (
        start !== undefined &&
        (other === undefined || weight(other) - weight(start) < START_CODES)
      ) {
        merged.push(start);
        i++;
      } else if (other !== undefined) {
        merged.push(other);
        j++;
      }
    }
    return merged;
  }

  /**
   * Readings to judge the order of names by at this level, or null when order
   * cannot matter: only on levels where every word is in the name. On exact
   * names every name is the words, so there only phrase order can differ,
   * and only when some reading has two or more words.
   */
  private orderReadings(level: number, readings: readonly Reading[]): Reading[] | null {
    if (level !== FULL && (level === STATE_ONLY || levelField(level) !== ALL_IN_NAME)) return null;
    const tier = level === FULL ? Tier.exact : levelTier(level);
    const usable = readings.filter((r) => r.words.length > 0 && tier >= r.floor);
    if (usable.length === 0) return null;
    if (level === FULL && !usable.some((r) => r.words.length > 1)) return null;
    return usable;
  }

  /**
   * Where a record's name has the words of one of its readings: where the
   * name starts (after a leading "the", as in "The Pembroke Hill School"),
   * side by side elsewhere, or apart. A single word is always side by side.
   */
  private wordsPlace(
    group: GroupData,
    rank: number,
    readings: readonly Reading[],
    words: readonly Word[],
    tier: TierValue,
  ): number {
    const state = (group.kindState[rank] ?? 0) & 63;
    const lists = readings
      .filter((reading) => reading.state < 0 || reading.state === state)
      .map((reading) =>
        reading.words.map((wi) => words[wi]).filter((w): w is Word => w !== undefined),
      );
    let place = WORDS_APART;
    for (const tokens of this.nameTokens(group, rank)) {
      if (tokens.length === 0) continue;
      const rest = tokens[0] === LEADING_ARTICLE ? tokens.slice(1) : null;
      const starts = lists.some(
        (list) =>
          isPhrase(tokens, list, tier, true) || (rest !== null && isPhrase(rest, list, tier, true)),
      );
      if (starts) return WORDS_START;
      if (lists.some((list) => isPhrase(tokens, list, tier))) place = WORDS_TOGETHER;
    }
    return place;
  }

  /** The tokens of a record's name, and of its shown name when it has one. */
  private nameTokens(group: GroupData, rank: number): string[][] {
    const file = group.fileIndex[rank] ?? 0;
    const names = [tokenize(this.index.name(file))];
    if ((group.shownCanon[rank] ?? 0) > 0) names.push(tokenize(this.index.shown(file)));
    return names;
  }

  /**
   * Whether a record's name has the words of one of its readings side by
   * side; with `atStart`, where the name starts.
   */
  private inPhrase(
    group: GroupData,
    rank: number,
    readings: readonly Reading[],
    words: readonly Word[],
    tier: TierValue,
    atStart = false,
  ): boolean {
    const state = (group.kindState[rank] ?? 0) & 63;
    const names = this.nameTokens(group, rank);
    return readings.some((reading) => {
      if (reading.state >= 0 && reading.state !== state) return false;
      const list = reading.words.map((wi) => words[wi]).filter((w): w is Word => w !== undefined);
      return names.some((tokens) => isPhrase(tokens, list, tier, atStart));
    });
  }

  /** Records at this level in any reading, or null when none can be. */
  private levelBits(
    level: number,
    g: number,
    group: GroupData,
    pool: BitPool,
    readings: readonly Reading[],
    words: readonly Word[],
  ): Uint32Array | null {
    let acc: Uint32Array | null = null;
    for (const reading of readings) {
      const bits = this.readingBits(level, g, group, pool, reading, words);
      if (!bits) continue;
      if (!acc) acc = bits;
      else orInto(acc, bits);
    }
    return acc;
  }

  private readingBits(
    level: number,
    g: number,
    group: GroupData,
    pool: BitPool,
    reading: Reading,
    words: readonly Word[],
  ): Uint32Array | null {
    const stateMask = reading.state >= 0 ? this.states.get(group, g, reading.state) : null;
    if (reading.words.length === 0) {
      // A query that is only a state name lists that state's places, after
      // everything that matched as text. A bare code ("pa") lists nothing.
      const listState = level === STATE_ONLY && stateMask && reading.named && g === CITIES;
      return listState ? pool.copy(stateMask) : null;
    }
    if (level === STATE_ONLY) return null;
    const tier = levelTier(level);
    if (tier < reading.floor) return null;
    if (tier === Tier.fuzzy && tier !== reading.floor) {
      // With no typo matches the typo levels equal the prefix levels, all of
      // which were already taken.
      const typos = reading.words.some((wi) => (words[wi]?.fuzzy(this.index).length ?? 0) > 0);
      if (!typos) return null;
    }
    const field = level === FULL ? ALL_IN_NAME : levelField(level);

    // Rarest word first, and stop as soon as nothing is left: a word that
    // matches nothing spares the work of every word after it.
    const order = reading.words
      .map((wi) => words[wi])
      .filter((w): w is Word => w !== undefined)
      .sort((a, b) => a.spread(group) - b.spread(group));
    const acc = pool.take();
    let first = true;
    for (const word of order) {
      const set = this.wordBits(word, g, group, pool, field === ALL_IN_NAME ? 0 : 1, tier);
      if (first) {
        acc.set(set);
        first = false;
      } else andInto(acc, set);
      if (isEmpty(acc)) return null;
    }
    if (stateMask) andInto(acc, stateMask);
    if (field === SOME_IN_NAME) {
      const anyName = pool.take();
      for (const wi of reading.words) {
        const word = words[wi];
        if (word) orInto(anyName, this.wordBits(word, g, group, pool, 0, tier));
      }
      andInto(acc, anyName);
    }
    if (level === FULL) {
      // The whole name: as many words as it has, or as its shown name has.
      const { canon, shownCanon } = group;
      for (let w = 0; w < acc.length; w++) {
        let x = acc[w] ?? 0;
        let keep = 0;
        while (x !== 0) {
          const low = x & -x;
          x ^= low;
          const rank = w * 32 + 31 - Math.clz32(low);
          if (canon[rank] === reading.canon || shownCanon[rank] === reading.canon) keep |= low;
        }
        acc[w] = keep;
      }
    }
    return isEmpty(acc) ? null : acc;
  }

  /** Records a word matches at a tier, in the name (field 0) or anywhere (field 1). */
  private wordBits(
    word: Word,
    g: number,
    group: GroupData,
    pool: BitPool,
    field: 0 | 1,
    tier: TierValue,
  ): Uint32Array {
    const key = g * 6 + field * 3 + tier;
    const cached = word.cache[key];
    if (cached) return cached;
    let bits: Uint32Array;
    if (field === 1) {
      if (!group.subOff) {
        bits = this.wordBits(word, g, group, pool, 0, tier);
      } else {
        bits = pool.copy(this.wordBits(word, g, group, pool, 0, tier));
        orInto(bits, this.placeBits(word, group, pool, tier));
      }
    } else if (tier === Tier.exact) {
      bits = pool.take();
      if (word.exact >= 0) {
        setPostings(bits, group.nameOff, group.namePost, word.exact, word.exact + 1);
      }
      for (const ids of word.expansions) this.addExpansion(bits, ids, group, pool, false);
    } else if (tier === Tier.prefix) {
      bits = pool.copy(this.wordBits(word, g, group, pool, 0, Tier.exact));
      setPostings(bits, group.nameOff, group.namePost, word.prefixLo, word.prefixHi);
    } else {
      const ranges = word.fuzzy(this.index);
      const prefix = this.wordBits(word, g, group, pool, 0, Tier.prefix);
      if (ranges.length === 0) bits = prefix;
      else {
        bits = pool.copy(prefix);
        for (let i = 0; i < ranges.length; i += 2) {
          setPostings(bits, group.nameOff, group.namePost, ranges[i] ?? 0, ranges[i + 1] ?? 0);
        }
      }
    }
    word.cache[key] = bits;
    return bits;
  }

  /** Records whose place part matches a word at a tier (schools group only). */
  private placeBits(word: Word, group: GroupData, pool: BitPool, tier: TierValue): Uint32Array {
    const bits = pool.take();
    if (word.exact >= 0) setPlaces(bits, this.index, group, word.exact, word.exact + 1);
    for (const ids of word.expansions) this.addExpansion(bits, ids, group, pool, true);
    if (tier >= Tier.prefix) setPlaces(bits, this.index, group, word.prefixLo, word.prefixHi);
    if (tier === Tier.fuzzy) {
      const ranges = word.fuzzy(this.index);
      for (let i = 0; i < ranges.length; i += 2) {
        setPlaces(bits, this.index, group, ranges[i] ?? 0, ranges[i + 1] ?? 0);
      }
    }
    return bits;
  }

  /** ORs into `bits` the records having every token in `ids` (in names, or places). */
  private addExpansion(
    bits: Uint32Array,
    ids: readonly number[],
    group: GroupData,
    pool: BitPool,
    places: boolean,
  ): void {
    let acc: Uint32Array | null = null;
    for (const id of ids) {
      const one = pool.take();
      if (places) setPlaces(one, this.index, group, id, id + 1);
      else setPostings(one, group.nameOff, group.namePost, id, id + 1);
      if (!acc) acc = one;
      else andInto(acc, one);
    }
    if (acc) orInto(bits, acc);
  }
}

/** [start, end) ranges of `rec.name` that match the query, merged and sorted. */
export function highlight(
  name: string,
  words: readonly { readonly text: string; readonly budget: number }[],
  tier: TierValue,
): [number, number][] {
  const spans: number[][] = [];
  const nameTokens = tokenize(name, spans);
  const ranges: [number, number][] = [];
  const mark = (j: number, chars: number): void => {
    const span = spans[j];
    if (!span || chars <= 0) return;
    const start = span[0] ?? 0;
    const end = span[Math.min(chars, span.length - 1)] ?? start;
    if (end > start) ranges.push([start, end]);
  };
  /** What each name token abbreviates, where it does ("HS": high school; "EL" at the end: elementary). */
  const abbreviates = nameTokens.map((t, j) =>
    (rulesStartingWith(t) ?? [])
      .filter(
        (rule) => rule.short.length === 1 && ruleHolds(nameTokens, 0, nameTokens.length, j, rule),
      )
      .map((rule) => rule.long),
  );
  for (const word of words) {
    const w = word.text;
    nameTokens.forEach((t, j) => {
      if (t === w) mark(j, t.length);
      else if (t.startsWith(w)) mark(j, w.length);
      else if ((abbreviates[j] ?? []).some((long) => long.some((l) => l.startsWith(w)))) {
        // The name abbreviates the word: "St." for "saint", "HS" for "high".
        mark(j, t.length);
      } else if (tier === Tier.fuzzy && word.budget > 0 && !isNumericToken(w)) {
        const d = prefixDistance(w, t);
        if (d.distance <= word.budget) mark(j, d.length);
      }
    });
    for (const expansion of queryExpansions(w)) {
      for (let j = 0; j + expansion.length <= nameTokens.length; j++) {
        if (expansion.every((e, k) => nameTokens[j + k] === e)) {
          for (let k = 0; k < expansion.length; k++) mark(j + k, nameTokens[j + k]?.length ?? 0);
        }
      }
    }
  }
  ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([r[0], r[1]]);
  }
  return merged;
}

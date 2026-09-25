/**
 * Runs queries against a loaded index.
 *
 * Each group (schools with districts, cities, ZIP codes) is ranked on its
 * own. A record's level is the best of:
 *
 *   0  exact name: every word matches a whole word and together they are the
 *      whole name ("lancaster" for the city Lancaster)
 *   then for each tier (exact, then prefix, then typo):
 *      all words in the name / some in the name, rest in the place / all in
 *      the place ("lancaster" for a school in Lancaster, PA)
 *   last  the query is only a state name
 *
 * and inside a level records come heaviest first, ties in index order, so the
 * output is stable. On levels where every word is in the name, a name holding
 * the words side by side in the order typed comes first ("ps 12" puts "PS 12
 * Lewis and Clark" ahead of "Public Schools ... K-12"; see phrase.ts), judged
 * over the level's heaviest PHRASE_WINDOW records. Sets are bitsets over each group's weight ranks: filling
 * one from a dictionary range is a single run over contiguous postings, and a
 * level is a few AND/OR passes, so the first `limit` set bits of each level
 * in rank order are the answer. Typo matching only runs when the exact and
 * prefix levels leave a group short.
 */
import type { GroupData, SearchIndex } from './decode';
import { isNumericToken, queryExpansions, tokenize, typoBudget } from './normalize';
import { isPhrase } from './phrase';
import { Tier, parseQuery } from './query';
import type { ParsedQuery, Reading, TierValue } from './query';
import { prefixDistance } from './trie';
import { GROUP_NAMES } from './types';
import type { GroupName, MatchKind, SearchHit, SearchResults } from './types';

export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 50;
/** Whole words this common are taken as spelled right: no typo matching for them. */
export const TYPO_RARE = 3;
/** Records per level, heaviest first, checked for phrase order. */
export const PHRASE_WINDOW = 64;

const CITIES = 1;
const FULL = 0;
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
}

export class SearchEngine {
  readonly index: SearchIndex;
  private readonly pools: readonly BitPool[];
  private readonly states = new StateMasks();

  constructor(index: SearchIndex) {
    this.index = index;
    this.pools = index.groups.map((g) => new BitPool(g.words));
  }

  search(raw: string, limit = DEFAULT_LIMIT): SearchResults {
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
        found.push(this.searchGroup(g, parsed, words, cap));
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
      const best = (g: number): number => found[g]?.[0]?.level ?? LEVEL_COUNT;
      order = [0, 1, 2]
        .sort((a, b) => best(a) - best(b) || a - b)
        .map((g) => GROUP_NAMES[g] ?? 'schools');
    }
    return { query: raw, schools, cities, zips, order };
  }

  private hit(g: number, f: Found, words: readonly Word[]): SearchHit {
    const group = this.index.groups[g];
    const rec = this.index.record(group?.fileIndex[f.rank] ?? 0);
    const tier = f.level === STATE_ONLY ? Tier.exact : levelTier(f.level);
    return {
      ...rec,
      match: MATCH_KIND[tier] ?? 'exact',
      highlight: highlight(rec.name, words, tier),
    };
  }

  private searchGroup(
    g: number,
    parsed: ParsedQuery,
    words: readonly Word[],
    cap: number,
  ): Found[] {
    const group = this.index.groups[g];
    const pool = this.pools[g];
    if (!group || !pool || group.size === 0) return [];
    const out: Found[] = [];
    const taken = (rank: number): boolean => out.some((f) => f.rank === rank);

    for (let level = 0; level < LEVEL_COUNT && out.length < cap; level++) {
      const bits = this.levelBits(level, g, group, pool, parsed.readings, words);
      if (!bits) continue;
      const phrased = this.phraseReadings(level, parsed.readings);
      // Without phrase order, take records straight off the set; with it,
      // take the level's heaviest few and put phrases first.
      const want = phrased ? Math.max(PHRASE_WINDOW, cap - out.length) : cap - out.length;
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
      if (phrased) {
        const tier = level === FULL ? Tier.exact : levelTier(level);
        const isFirst = ranks.map((rank) => this.inPhrase(group, rank, phrased, words, tier));
        for (const first of [true, false]) {
          ranks.forEach((rank, k) => {
            if (isFirst[k] === first && out.length < cap) out.push({ rank, level });
          });
        }
      } else {
        for (const rank of ranks) out.push({ rank, level });
      }
    }
    return out;
  }

  /**
   * Readings to judge phrase order by at this level, or null when order
   * cannot matter: only on levels where every word is in the name, and only
   * when some reading has two or more words.
   */
  private phraseReadings(level: number, readings: readonly Reading[]): Reading[] | null {
    if (level !== FULL && (level === STATE_ONLY || levelField(level) !== ALL_IN_NAME)) return null;
    const tier = level === FULL ? Tier.exact : levelTier(level);
    const usable = readings.filter((r) => r.words.length > 0 && tier >= r.floor);
    return usable.some((r) => r.words.length > 1) ? usable : null;
  }

  /** Whether a record's name has the words of one of its readings side by side. */
  private inPhrase(
    group: GroupData,
    rank: number,
    readings: readonly Reading[],
    words: readonly Word[],
    tier: TierValue,
  ): boolean {
    const state = (group.kindState[rank] ?? 0) & 63;
    const tokens = tokenize(this.index.name(group.fileIndex[rank] ?? 0));
    return readings.some((reading) => {
      if (reading.state >= 0 && reading.state !== state) return false;
      const list = reading.words.map((wi) => words[wi]).filter((w): w is Word => w !== undefined);
      return isPhrase(tokens, list, tier);
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
      const canon = group.canon;
      for (let w = 0; w < acc.length; w++) {
        let x = acc[w] ?? 0;
        let keep = 0;
        while (x !== 0) {
          const low = x & -x;
          x ^= low;
          const rank = w * 32 + 31 - Math.clz32(low);
          if (canon[rank] === reading.canon) keep |= low;
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
  for (const word of words) {
    const w = word.text;
    nameTokens.forEach((t, j) => {
      if (t === w) mark(j, t.length);
      else if (t.startsWith(w)) mark(j, w.length);
      else if (queryExpansions(t).some((long) => long.some((l) => l.startsWith(w)))) {
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

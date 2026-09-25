/**
 * Turns raw search input into the words to match and the ways to read it.
 *
 * A query can end with a state ("lancaster pa", "lancaster, pennsylvania",
 * "new york ny"). Each state its last words can name gives an extra reading
 * in which those words filter by state instead of matching text. The engine
 * ranks every record by its best reading, so "washington pa" finds
 * Washington, Pennsylvania as well as schools named Washington Park. Only the
 * end counts: people write the place, then the state, and reading a state at
 * the start would turn "washington pa" into places in Washington state.
 */
import { canonicalLength, isNumericToken, tokenize, typoBudget } from './normalize';
import { STATES } from './states';
import { editDistance } from './trie';

/** Input past this many UTF-16 code units is ignored. */
export const MAX_QUERY_CHARS = 256;
/** Words past this many are ignored. */
export const MAX_QUERY_WORDS = 8;
/** At most this many state readings are tried besides the plain one. */
const MAX_STATE_READINGS = 6;
/** Longest state name, in words ("district of columbia"). */
const MAX_STATE_WORDS = 3;

/** Match tiers, best first. */
export const Tier = { exact: 0, prefix: 1, fuzzy: 2 } as const;
export type TierValue = (typeof Tier)[keyof typeof Tier];

export interface Reading {
  /** Indexes into ParsedQuery.words of the words matched as text. */
  readonly words: readonly number[];
  /** State index (see states.ts) the reading filters by, or -1. */
  readonly state: number;
  /** Tier the state words matched at; no match in this reading ranks above it. */
  readonly floor: TierValue;
  /** Word count of the text words with abbreviations spelled out. */
  readonly canon: number;
  /** True when the state was named in full rather than by its code. */
  readonly named: boolean;
}

export interface ParsedQuery {
  /** Distinct words in input order. */
  readonly words: readonly string[];
  /** True when every word is a number, as when typing a ZIP code. */
  readonly numeric: boolean;
  /** The plain reading first, then state readings, best first. */
  readonly readings: readonly Reading[];
}

interface StateName {
  readonly index: number;
  readonly code: string;
  readonly name: string;
}

const STATE_NAMES: readonly StateName[] = STATES.map(([code, name], index) => ({
  index,
  code: code.toLowerCase(),
  name: tokenize(name).join(' '),
}));

const ZIP_PLUS_FOUR = /\b(\d{5})-\d{4}\b/g;

interface StateMatch {
  readonly state: number;
  readonly tier: TierValue;
  readonly named: boolean;
}

interface Span extends StateMatch {
  readonly from: number;
  readonly to: number;
}

/**
 * States the last words of a query can name: a USPS code, a full name, the
 * start of a name while it is still being typed (`open`: nothing typed after
 * it yet), or a name with typos.
 */
function statesFor(text: string, words: number, open: boolean): StateMatch[] {
  const found: StateMatch[] = [];
  const budget = typoBudget(text.replaceAll(' ', ''));
  for (const s of STATE_NAMES) {
    if (words === 1 && text.length === 2 && text === s.code) {
      found.push({ state: s.index, tier: Tier.exact, named: false });
    } else if (text === s.name) {
      found.push({ state: s.index, tier: Tier.exact, named: true });
    } else if (open && text.length >= 3 && s.name.startsWith(text)) {
      found.push({ state: s.index, tier: Tier.prefix, named: true });
    } else if (budget > 0 && text.length >= 4 && editDistance(text, s.name) <= budget) {
      found.push({ state: s.index, tier: Tier.fuzzy, named: true });
    }
  }
  return found;
}

/** Input that ends in a separator: the last word is finished. */
const FINISHED = /[\s,;.]$/u;

/** Parses raw input. Empty or symbol-only input gives no words and no readings. */
export function parseQuery(raw: string): ParsedQuery {
  const text = raw.slice(0, MAX_QUERY_CHARS).replace(ZIP_PLUS_FOUR, '$1');
  const all = tokenize(text).slice(0, MAX_QUERY_WORDS);
  const words: string[] = [];
  const position: number[] = []; // token position to index in words
  for (const t of all) {
    let at = words.indexOf(t);
    if (at < 0) {
      at = words.length;
      words.push(t);
    }
    position.push(at);
  }
  if (all.length === 0) return { words, numeric: false, readings: [] };

  const readingFor = (
    from: number,
    to: number,
    state: number,
    floor: TierValue,
    named: boolean,
  ): Reading => {
    const kept: number[] = [];
    const keptTokens: string[] = [];
    for (let i = 0; i < all.length; i++) {
      if (i >= from && i < to) continue;
      keptTokens.push(all[i] ?? '');
      const w = position[i] ?? 0;
      if (!kept.includes(w)) kept.push(w);
    }
    return { words: kept, state, floor, canon: canonicalLength(keptTokens), named };
  };

  const readings: Reading[] = [readingFor(0, 0, -1, Tier.exact, false)];
  const open = !FINISHED.test(text);
  const n = all.length;
  const spans: Span[] = [];
  for (let len = 1; len <= Math.min(MAX_STATE_WORDS, n); len++) {
    const from = n - len;
    const spanText = all.slice(from, n).join(' ');
    for (const hit of statesFor(spanText, len, open)) spans.push({ ...hit, from, to: n });
  }
  // Best tier first, then the longer span ("new york" before "york").
  spans.sort((a, b) => a.tier - b.tier || a.from - b.from);
  // A code only reads as a state after a word of three or more characters:
  // "lancaster pa" is Pennsylvania, but "st ma" is someone typing "St. Mary".
  const placeWord = (to: number): boolean => all.slice(0, to).some((t) => t.length >= 3);
  const usable = spans.filter((span) => span.named || placeWord(span.from));
  for (const span of usable.slice(0, MAX_STATE_READINGS)) {
    readings.push(readingFor(span.from, span.to, span.state, span.tier, span.named));
  }
  return { words, numeric: all.every(isNumericToken), readings };
}

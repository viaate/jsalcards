/**
 * Phrase order: whether a name holds the query words side by side, in the
 * order typed. The engine's sets only know which words a record has, so
 * "ps 12" finds both "PS 12 Lewis and Clark" and "Pulaski County Public
 * Schools Virtual School K-12"; the engine uses this to put the first kind
 * ahead of the second within a level.
 *
 * Both sides may be abbreviated: a query word can stand for its full words
 * ("hs" for "high school") and a name token for its own ("St." for "saint",
 * "HS" for "high school"), so "jefferson hs", "jefferson high school" and
 * "jefferson high" all read as phrases of "Jefferson HS" and of "Jefferson
 * High School". The query may stop partway through a name's abbreviation.
 */
import { isNumericToken, queryExpansions, rulesStartingWith } from './normalize';
import { Tier } from './query';
import type { TierValue } from './query';
import { prefixDistance } from './trie';

/** A query word as the engine holds it. */
export interface PhraseWord {
  readonly text: string;
  /** Edits allowed at the typo tier. */
  readonly budget: number;
}

/** Steps one check may take before giving up; real names need a few dozen. */
const STEP_BUDGET = 4000;

/** One way to read a stretch of name tokens: the words it stands for. */
interface Edge {
  readonly consume: number;
  readonly words: readonly string[];
}

/** One way to read a query word: itself, matched at the tier, or its full words, matched exactly. */
interface Unit {
  readonly words: readonly string[];
  readonly literal: boolean;
}

/** Whether a typed word matches a name word at a tier, as the engine's sets do. */
export function wordMatches(word: PhraseWord, token: string, tier: TierValue): boolean {
  if (token === word.text) return true;
  if (tier === Tier.exact) return false;
  if (token.startsWith(word.text)) return true;
  if (tier !== Tier.fuzzy || word.budget === 0 || isNumericToken(word.text)) return false;
  return prefixDistance(word.text, token).distance <= word.budget;
}

function nameEdges(tokens: readonly string[]): Edge[][] {
  return tokens.map((t, j) => {
    const edges: Edge[] = [{ consume: 1, words: [t] }];
    for (const rule of rulesStartingWith(t) ?? []) {
      const n = rule.short.length;
      if (j + n > tokens.length) continue;
      let ok = true;
      for (let k = 1; k < n && ok; k++) ok = tokens[j + k] === rule.short[k];
      if (ok) edges.push({ consume: n, words: rule.long });
    }
    return edges;
  });
}

function queryUnits(words: readonly PhraseWord[]): Unit[][] {
  return words.map((w) => [
    { words: [w.text], literal: true },
    ...queryExpansions(w.text).map((long) => ({ words: long, literal: false })),
  ]);
}

/**
 * True when `words` match consecutive tokens of `tokens` in order, each at
 * `tier` or better. A single word only needs to match somewhere.
 */
export function isPhrase(
  tokens: readonly string[],
  words: readonly PhraseWord[],
  tier: TierValue,
): boolean {
  const m = words.length;
  const n = tokens.length;
  if (m === 0) return true;
  if (n === 0) return false;
  const edges = nameEdges(tokens);
  const units = queryUnits(words);
  let steps = 0;

  // i: next query word; unit, qk: the query unit being matched and how far;
  // j: next name token; edge, nk: the name edge being matched and how far.
  const step = (
    i: number,
    unit: Unit | null,
    qk: number,
    j: number,
    edge: Edge | null,
    nk: number,
  ): boolean => {
    if (++steps > STEP_BUDGET) return false;
    if (!unit || qk === unit.words.length) {
      // The query ran out, perhaps partway through a name abbreviation.
      if (i === m) return true;
      for (const next of units[i] ?? []) {
        if (step(i + 1, next, 0, j, edge, nk)) return true;
      }
      return false;
    }
    if (!edge || nk === edge.words.length) {
      if (j >= n) return false;
      for (const next of edges[j] ?? []) {
        if (step(i, unit, qk, j + next.consume, next, 0)) return true;
      }
      return false;
    }
    const q = unit.words[qk] ?? '';
    const t = edge.words[nk] ?? '';
    const word = words[i - 1];
    const ok = unit.literal && word ? wordMatches(word, t, tier) : q === t;
    return ok && step(i, unit, qk + 1, j, edge, nk + 1);
  };

  for (let start = 0; start < n; start++) {
    if (step(0, null, 0, start, null, 0)) return true;
    if (steps > STEP_BUDGET) return false;
  }
  return false;
}

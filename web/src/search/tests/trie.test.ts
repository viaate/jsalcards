// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { Dictionary, TokenTrie, editDistance, prefixDistance } from '../trie';
import { mulberry32 } from './random';

function build(tokens: string[]): { trie: TokenTrie; sorted: string[] } {
  const sorted = [...new Set(tokens)].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return { trie: new TokenTrie(Dictionary.fromTokens(sorted)), sorted };
}

function randomWords(seed: number, count: number, alphabet = 'abcde'): string[] {
  const random = mulberry32(seed);
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    let w = '';
    const len = 1 + Math.floor(random() * 9);
    for (let k = 0; k < len; k++) w += alphabet[Math.floor(random() * alphabet.length)] ?? 'a';
    out.push(w);
  }
  return out;
}

function covered(ranges: readonly number[], id: number): boolean {
  for (let i = 0; i < ranges.length; i += 2) {
    if (id >= (ranges[i] ?? 0) && id < (ranges[i + 1] ?? 0)) return true;
  }
  return false;
}

describe('TokenTrie', () => {
  const { trie, sorted } = build([
    'lancaster',
    'lancasterville',
    'lance',
    'lancer',
    'lincoln',
    'la',
    'school',
    'sch',
    'schools',
  ]);

  it('finds exact tokens', () => {
    expect(sorted[trie.exact('lancaster')]).toBe('lancaster');
    expect(sorted[trie.exact('sch')]).toBe('sch');
    expect(trie.exact('lanc')).toBe(-1);
    expect(trie.exact('zebra')).toBe(-1);
    expect(trie.exact('')).toBe(-1);
  });

  it('gives each prefix one contiguous range', () => {
    const [lo, hi] = trie.prefix('lanc');
    expect(sorted.slice(lo, hi)).toEqual(['lancaster', 'lancasterville', 'lance', 'lancer']);
    const [slo, shi] = trie.prefix('sch');
    expect(sorted.slice(slo, shi)).toEqual(['sch', 'school', 'schools']);
    expect(trie.prefix('zz')).toEqual([0, 0]);
    expect(trie.prefix('')).toEqual([0, sorted.length]);
  });

  it('refuses an unsorted dictionary', () => {
    expect(() => new TokenTrie(Dictionary.fromTokens(['b', 'a', 'a']))).toThrow();
  });

  it('matches brute force for exact and prefix lookups', () => {
    const words = randomWords(3, 400);
    const t = build(words);
    for (const q of randomWords(4, 300)) {
      expect(t.trie.exact(q)).toBe(t.sorted.indexOf(q));
      const [lo, hi] = t.trie.prefix(q);
      const expected = t.sorted.filter((w) => w.startsWith(q));
      expect(t.sorted.slice(lo, hi)).toEqual(expected);
    }
  });

  it.each([1, 2])('matches brute force for typo prefixes within %i edits', (k) => {
    const t = build(randomWords(5, 500, 'abcdef'));
    for (const q of randomWords(6, 200, 'abcdef').filter((w) => w.length >= 3)) {
      const ranges: number[] = [];
      t.trie.fuzzy(q, k, ranges);
      t.sorted.forEach((w, id) => {
        const within = prefixDistance(q, w).distance <= k;
        expect(covered(ranges, id), `${q} vs ${w}`).toBe(within);
      });
    }
  });

  it('counts a transposition as one edit', () => {
    const out: number[] = [];
    trie.fuzzy('lnacaster', 1, out);
    expect(covered(out, sorted.indexOf('lancaster'))).toBe(true);
  });
});

describe('edit distances', () => {
  it.each([
    ['lancaster', 'lancaster', 0],
    ['lancster', 'lancaster', 1],
    ['lnacaster', 'lancaster', 1],
    ['lancasterr', 'lancaster', 1],
    ['lnacstre', 'lancaster', 3],
    ['', 'abc', 3],
    ['abc', '', 3],
    ['ca', 'abc', 3],
  ])('%j to %j is %i', (a, b, d) => {
    expect(editDistance(a, b)).toBe(d);
  });

  it('finds the closest prefix', () => {
    expect(prefixDistance('lanc', 'lancaster')).toEqual({ distance: 0, length: 4 });
    expect(prefixDistance('lnac', 'lancaster')).toEqual({ distance: 1, length: 4 });
    expect(prefixDistance('lancastr', 'lancaster')).toEqual({ distance: 1, length: 9 });
    expect(prefixDistance('xyz', 'lancaster').distance).toBe(3);
  });
});

// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { loadIndex } from '../decode';
import { encodeIndex } from '../encode';
import { PHRASE_WINDOW, SearchEngine } from '../engine';
import { tokenize, typoBudget } from '../normalize';
import { isPhrase, wordMatches } from '../phrase';
import { Tier } from '../query';
import type { TierValue } from '../query';
import type { SearchRecord } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

function phrase(name: string, query: string, tier: TierValue = Tier.exact): boolean {
  const words = [...new Set(tokenize(query))].map((text) => ({ text, budget: typoBudget(text) }));
  return isPhrase(tokenize(name), words, tier);
}

describe('isPhrase', () => {
  it.each([
    ['PS 12 Harbor View', 'ps 12'],
    ['P.S. 12 Harbor View', 'ps 12'],
    ['Harbor View PS 12', 'ps 12'],
    ['Lincoln Elementary', 'lincoln elem'],
    ['Lincoln Elem', 'lincoln elementary'],
    ['Lincoln Elem', 'lincoln elem'],
    ['Jefferson High School', 'jefferson hs'],
    ['Jefferson HS', 'jefferson high school'],
    ['Jefferson HS', 'jefferson high'],
    ['Thomas Jefferson HS', 'jefferson high'],
    ['Saint Marys Academy', 'st marys'],
    ["St. Mary's School", 'saint marys'],
    ['Main St Elementary', 'main street'],
    ['Hans Herr El Sch', 'herr elementary school'],
    ['Hans Herr El Sch', 'herr elementary'],
    ['Oak Hill Elementary School', 'hill elementary'],
    ['Oak Hill Elementary School', 'oak'],
    ['Arts & Sciences Academy', 'arts and sciences'],
  ])('reads "%s" as a phrase of "%s"', (name, query) => {
    expect(phrase(name, query)).toBe(true);
  });

  it.each([
    ['Pine County Public Schools Online School K-12', 'ps 12'],
    ['Ridge High School Central', 'central high'],
    ['School of Lincoln Elementary Arts', 'elementary lincoln'],
    ['South Oak Street Hill Elementary', 'oak hill'],
    ['Oak Hill Elementary School', 'oak elementary'],
    ['Jefferson High', 'jefferson hs'],
    ['Oak Hill', 'hill oak'],
  ])('does not read "%s" as a phrase of "%s"', (name, query) => {
    expect(phrase(name, query)).toBe(false);
  });

  it('follows the tier: prefixes only from the prefix tier, typos only at the typo tier', () => {
    expect(phrase('Lancaster High School', 'lanc high', Tier.exact)).toBe(false);
    expect(phrase('Lancaster High School', 'lanc high', Tier.prefix)).toBe(true);
    expect(phrase('Lancaster High School', 'lancastr high', Tier.prefix)).toBe(false);
    expect(phrase('Lancaster High School', 'lancastr high', Tier.fuzzy)).toBe(true);
    // Numbers never match with typos.
    expect(phrase('PS 12 Harbor View', 'ps 13', Tier.fuzzy)).toBe(false);
  });

  it('lets the query stop partway through a name abbreviation', () => {
    expect(phrase('Jefferson HS', 'jefferson hig', Tier.prefix)).toBe(true);
    expect(phrase('Jefferson HS', 'jefferson school')).toBe(false);
  });

  it('handles empty and single-word input', () => {
    expect(isPhrase(['oak'], [], Tier.exact)).toBe(true);
    expect(isPhrase([], [{ text: 'oak', budget: 0 }], Tier.exact)).toBe(false);
    expect(phrase('Oak Hill', 'hill')).toBe(true);
    expect(phrase('Oak Hill', 'pine')).toBe(false);
  });

  it('gives up quickly on pathological input', () => {
    const name = Array.from({ length: 40 }, () => 'st').join(' ');
    const query = Array.from({ length: 8 }, (_, i) => (i === 7 ? 'zzz' : 'st')).join(' ');
    const words = tokenize(query).map((text) => ({ text, budget: 0 }));
    const t0 = performance.now();
    expect(isPhrase(tokenize(name), words, Tier.fuzzy)).toBe(false);
    expect(performance.now() - t0).toBeLessThan(50);
  });

  it('matches words the way the engine does', () => {
    expect(wordMatches({ text: 'lanc', budget: 1 }, 'lancaster', Tier.exact)).toBe(false);
    expect(wordMatches({ text: 'lanc', budget: 1 }, 'lancaster', Tier.prefix)).toBe(true);
    expect(wordMatches({ text: 'lncaster', budget: 2 }, 'lancaster', Tier.fuzzy)).toBe(true);
    expect(wordMatches({ text: 'lncaster', budget: 2 }, 'lancaster', Tier.prefix)).toBe(false);
  });
});

/** SYNTHETIC records for phrase order; made up for this test only. */
function syn(id: string, name: string, state: string, weight: number): SearchRecord {
  return {
    kind: 'school',
    id: `SYNP${id}`,
    name,
    sub: `Harbor, ${state}`,
    state,
    lat: 40,
    lon: -75,
    weight,
  };
}

const PHRASE_RECORDS: readonly SearchRecord[] = [
  syn('01', 'Pine County Public Schools Online School K-12', 'VA', 5000),
  syn('02', 'PS 12 Harbor View', 'NY', 400),
  syn('03', 'PS 12 Maple Grove', 'NY', 300),
  syn('04', 'PS 128 Maple', 'NY', 900),
  syn('05', 'Ridge High School Central', 'OH', 3000),
  syn('06', 'Central High School', 'OH', 500),
  syn('07', 'Central Ridge High School', 'OH', 200),
  syn('08', 'Harbor Oak Academy', 'PA', 800),
  syn('09', 'Oak Harbor Academy', 'PA', 100),
];

const engine = new SearchEngine(loadIndex(encodeIndex(PHRASE_RECORDS).bytes));

function names(q: string, limit?: number): string[] {
  return engine.search(q, limit).schools.map((h) => h.name);
}

describe('phrase order in the engine', () => {
  it('puts a name with the words side by side ahead of a heavier scattered match', () => {
    expect(names('ps 12')).toEqual([
      'PS 12 Harbor View',
      'PS 12 Maple Grove',
      'Pine County Public Schools Online School K-12',
      'PS 128 Maple',
    ]);
    expect(names('p.s. 12')).toEqual(names('ps 12'));
  });

  it('keeps weight order among phrases and among the rest', () => {
    expect(names('central high')).toEqual([
      'Central High School',
      'Ridge High School Central',
      'Central Ridge High School',
    ]);
  });

  it('follows the order typed', () => {
    expect(names('harbor oak')[0]).toBe('Harbor Oak Academy');
    expect(names('oak harbor')[0]).toBe('Oak Harbor Academy');
  });

  it('leaves one-word queries in weight order', () => {
    expect(names('harbor')).toEqual([
      'Harbor Oak Academy',
      'PS 12 Harbor View',
      'Oak Harbor Academy',
      // Named elsewhere, in Harbor.
      'Pine County Public Schools Online School K-12',
      'Ridge High School Central',
    ]);
  });

  it('keeps the match kind of the level', () => {
    const r = engine.search('ps 12').schools;
    expect(r.map((h) => h.match)).toEqual(['exact', 'exact', 'exact', 'prefix']);
  });

  it('judges a state reading by its own words', () => {
    // "harbor oak pa": the state reading's words are "harbor oak".
    expect(names('harbor oak pa')[0]).toBe('Harbor Oak Academy');
    expect(names('oak harbor pa')[0]).toBe('Oak Harbor Academy');
  });
});

describe('phrase order is stable', () => {
  const fixture = new SearchEngine(loadIndex(encodeIndex(SYNTHETIC_RECORDS).bytes));
  it.each([
    'ps 12',
    'lincoln high',
    'oak hill elementary',
    'lancaster high school',
    'st marys',
    'springfield il',
    'high school',
    'lanc hi',
  ])('a smaller limit gives a prefix of a larger one for "%s"', (q) => {
    for (const e of [engine, fixture]) {
      const big = e.search(q, 50);
      const small = e.search(q, 3);
      for (const g of ['schools', 'cities', 'zips'] as const) {
        expect(big[g].slice(0, small[g].length).map((h) => h.id)).toEqual(
          small[g].map((h) => h.id),
        );
      }
      expect(e.search(q, 50)).toEqual(big);
    }
  });

  it('judges only the heaviest records of a level', () => {
    // More scattered matches than the window, all heavier than the one phrase.
    const heavy = Array.from({ length: PHRASE_WINDOW + 5 }, (_, i) =>
      syn(`H${String(i)}`, `Delta School Gamma ${String(i)}`, 'NY', 10_000 - i),
    );
    const light = syn('L1', 'Gamma Delta School', 'NY', 1);
    const e = new SearchEngine(loadIndex(encodeIndex([...heavy, light]).bytes));
    const top = e.search('gamma delta', 50).schools.map((h) => h.name);
    expect(top).toHaveLength(50);
    expect(top).not.toContain('Gamma Delta School');
    // Within the window a phrase still wins.
    const few = heavy.slice(0, PHRASE_WINDOW - 1);
    const f = new SearchEngine(loadIndex(encodeIndex([...few, light]).bytes));
    expect(f.search('gamma delta').schools[0]?.name).toBe('Gamma Delta School');
  });
});

// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { loadIndex } from '../decode';
import { encodeIndex } from '../encode';
import { DEFAULT_LIMIT, SearchEngine, highlight } from '../engine';
import type { GroupName, SearchResults } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

const engine = new SearchEngine(loadIndex(encodeIndex(SYNTHETIC_RECORDS).bytes));

function ids(q: string, group: GroupName, limit?: number): string[] {
  return engine.search(q, limit)[group].map((h) => h.id);
}

function first(q: string, group: GroupName) {
  return engine.search(q)[group][0];
}

function total(r: SearchResults): number {
  return r.schools.length + r.cities.length + r.zips.length;
}

describe('matching', () => {
  it('ranks an exact name first, then heavier matches', () => {
    // Every city named exactly Lancaster, heaviest first; New Lancaster
    // matches a whole word too but is not the whole name.
    expect(ids('lancaster', 'cities')).toEqual(['SYNC02', 'SYNC01', 'SYNC04', 'SYNC03', 'SYNC05']);
  });

  it('puts exact before prefix before typo', () => {
    const r = engine.search('lancaster', 10).schools;
    const kinds = r.map((h) => h.match);
    expect(kinds.indexOf('prefix')).toBeGreaterThan(kinds.lastIndexOf('exact'));
    expect(r.find((h) => h.name === 'Lancasterville Elementary School')?.match).toBe('prefix');
  });

  it('matches every word as a prefix', () => {
    expect(first('lanc high', 'schools')?.name).toBe('Lancaster High School');
    expect(first('spr hi', 'schools')?.name).toBe('Springfield High School');
  });

  it('ranks names above places', () => {
    const r = engine.search('lancaster', 10).schools.map((h) => h.name);
    // McCaskey is in Lancaster but not named for it: after every named match.
    expect(r.indexOf('McCaskey Campus')).toBeGreaterThan(r.indexOf('Lancaster Mennonite School'));
    expect(r).toContain('McCaskey Campus');
  });

  it('finds a school by its place', () => {
    expect(ids('mccaskey lancaster', 'schools')).toEqual(['SYNS03']);
  });

  it('needs every word to match', () => {
    expect(engine.search('lancaster zebra').schools).toEqual([]);
  });

  it('ignores word order and case', () => {
    expect(ids('HIGH lancaster', 'schools')[0]).toBe('SYNS01');
  });

  it('keeps ties in a stable order', () => {
    expect(ids('oak hill', 'schools')).toEqual(['SYNS21', 'SYNS22', 'SYNS23']);
    expect(ids('oak hill', 'schools')).toEqual(ids('oak hill', 'schools'));
  });

  it('returns at most five per group by default', () => {
    expect(DEFAULT_LIMIT).toBe(5);
    expect(engine.search('school').schools).toHaveLength(5);
    expect(engine.search('school', 12).schools.length).toBeGreaterThan(5);
    expect(engine.search('school', 0).schools).toHaveLength(5);
    expect(engine.search('school', 1000).schools.length).toBeLessThanOrEqual(50);
  });

  it('echoes the query', () => {
    expect(engine.search('  Lancaster ').query).toBe('  Lancaster ');
  });
});

describe('typos', () => {
  it.each([
    ['lancastr', 'SYNC02'],
    ['lnacaster', 'SYNC02'],
    ['lancasterr', 'SYNC02'],
    ['philadelpia', 'SYNC19'],
    ['pitsburgh', 'SYNC18'],
    ['springfeild', 'SYNC07'],
  ])('%j finds %s', (q, id) => {
    const hit = first(q, 'cities');
    expect(hit?.id).toBe(id);
    expect(hit?.match).toBe('fuzzy');
  });

  it('allows two typos from eight characters', () => {
    expect(first('lncastre', 'cities')?.id).toBe('SYNC02');
  });

  it('allows one typo from four characters but not two', () => {
    expect(first('oakk hill', 'schools')?.name).toBe('Oak Hill Elementary School');
    expect(first('oak hilk', 'schools')?.name).toBe('Oak Hill Elementary School');
    expect(engine.search('oakkk hill').schools).toEqual([]);
  });

  it('allows no typo below four characters', () => {
    expect(engine.search('oxk').schools).toEqual([]);
  });

  it('corrects a typo that starts real words', () => {
    // "hight" starts no fixture word, but would still be read as "high".
    expect(first('hight school lancaster', 'schools')?.name).toBe('Lancaster High School');
    expect(first('lancastr hig', 'schools')?.name).toBe('Lancaster High School');
  });

  it('does not bend a common word into another', () => {
    // "portland" is spelled right: no Orlando.
    expect(ids('portland', 'cities')).toEqual(['SYNC14', 'SYNC15']);
  });

  it('never bends numbers', () => {
    expect(engine.search('17610').zips).toEqual([]);
  });
});

describe('states', () => {
  it.each(['lancaster pa', 'lancaster, pa', 'lancaster pennsylvania', 'lancaster, pennsylvania'])(
    '%j finds Lancaster, PA first',
    (q) => {
      expect(first(q, 'cities')?.id).toBe('SYNC01');
      expect(first(q, 'schools')?.sub).toBe('Lancaster, PA');
    },
  );

  it('keeps the plain reading too', () => {
    // "washington pa": Washington, PA and Washington Park.
    const cities = ids('washington pa', 'cities');
    expect(cities[0]).toBe('SYNC10');
    expect(cities).toContain('SYNC11');
  });

  it('reads multi-word state names', () => {
    expect(ids('new york new york', 'cities')[0]).toBe('SYNC08');
    expect(first('new york ny', 'cities')?.id).toBe('SYNC08');
  });

  it('reads a misspelled or unfinished state name', () => {
    expect(first('lancaster pensylvania', 'cities')?.id).toBe('SYNC01');
    expect(first('lancaster penn', 'cities')?.id).toBe('SYNC01');
  });

  it('lists a state by name when nothing else matches', () => {
    const cities = engine.search('pennsylvania').cities.map((h) => h.state);
    expect(cities.length).toBeGreaterThan(0);
    expect(new Set(cities)).toEqual(new Set(['PA']));
  });

  it('does not list a state for a bare code', () => {
    expect(engine.search('pa').cities.every((h) => h.name.toLowerCase().includes('pa'))).toBe(true);
  });

  it('keeps "st ma" for saints', () => {
    // Someone typing "St. Mary", not asking for Massachusetts.
    const names = engine.search('st ma').schools.map((h) => h.name);
    expect(names).toEqual(['Saint Marys Academy', "St. Mary's School"]);
  });
});

describe('ZIP codes', () => {
  it('finds a ZIP exactly', () => {
    expect(ids('17601', 'zips')).toEqual(['17601']);
    expect(first('17601', 'zips')?.match).toBe('exact');
  });

  it('finds ZIPs by prefix, in order', () => {
    expect(ids('176', 'zips')).toEqual(['17601', '17602', '17603']);
    expect(ids('17', 'zips')).toEqual(['17601', '17602', '17603', '17701']);
  });

  it('keeps leading zeros', () => {
    expect(ids('010', 'zips')).toEqual(['01002']);
  });

  it('puts ZIPs first for numeric input', () => {
    expect(engine.search('176').order).toEqual(['zips', 'schools', 'cities']);
    expect(engine.search('17601-1234').zips[0]?.id).toBe('17601');
  });

  it('still finds numbered schools', () => {
    expect(first('123', 'schools')?.name).toBe('P.S. 123 Mahalia Jackson');
  });

  it('filters ZIPs by state', () => {
    expect(ids('176 pa', 'zips')).toEqual(['17601', '17602', '17603']);
  });
});

describe('abbreviations', () => {
  it.each([
    ['lincoln hs', 'Lincoln HS'],
    ['lincoln high school', 'Lincoln HS'],
    ['lincoln hs', 'Lincoln High School'],
    ['lincoln elementary', 'Lincoln Elem'],
    ['lincoln elem', 'Lincoln Elem'],
    ['hans herr elementary school', 'Hans Herr El Sch'],
    ["saint mary's", "St. Mary's School"],
    ['st marys', 'Saint Marys Academy'],
    ['mount vernon', 'Mt. Vernon Intermediate School'],
    ['mt vernon is', 'Mt. Vernon Intermediate School'],
    ['lancaster independent school district', 'Lancaster ISD'],
    ['arts and sciences', 'Arts & Sciences Academy'],
    ['arts & sciences', 'Arts & Sciences Academy'],
  ])('%j finds %s', (q, name) => {
    expect(engine.search(q, 10).schools.map((h) => h.name)).toContain(name);
  });

  it('treats a spelled-out name as the whole name', () => {
    const cities = engine.search('saint marys').cities;
    expect(cities[0]?.name).toBe('St. Marys');
    expect(cities[0]?.match).toBe('exact');
  });
});

describe('accents and punctuation', () => {
  it.each([
    ['canon city', 'SYNC12'],
    ['cañon city', 'SYNC12'],
    ['CAÑON CITY', 'SYNC12'],
    ['cañon', 'SYNC12'],
  ])('%j finds Cañon City', (q, id) => {
    expect(first(q, 'cities')?.id).toBe(id);
  });

  it.each([
    ['espanola', 'Española Valley High School'],
    ["o'neill", "O'Neill Middle School"],
    ['oneill', "O'Neill Middle School"],
    ['o neill', "O'Neill Middle School"],
    ['p.s. 123', 'P.S. 123 Mahalia Jackson'],
    ['ps 123', 'P.S. 123 Mahalia Jackson'],
  ])('%j finds %s', (q, name) => {
    expect(engine.search(q, 10).schools.map((h) => h.name)).toContain(name);
  });
});

describe('odd input', () => {
  it.each([
    '',
    ' ',
    '     \t  ',
    '🙂',
    '🏫🏫🏫',
    '---',
    '\u0000\u0001',
    '\ud800',
    '學校',
    'x'.repeat(10_000),
    'lancaster '.repeat(200),
    '%%%***',
  ])('handles %j without error', (q) => {
    const r = engine.search(q);
    expect(r.query).toBe(q);
    expect(total(r)).toBeLessThanOrEqual(15);
  });

  it('finds nothing for input without words', () => {
    expect(total(engine.search('🙂 ---'))).toBe(0);
    expect(total(engine.search('   '))).toBe(0);
  });

  it('matches text around emoji', () => {
    expect(first('🏫 lancaster 🏫', 'cities')?.id).toBe('SYNC02');
  });
});

describe('results', () => {
  it('carries what the detail panel needs', () => {
    const hit = first('mccaskey', 'schools');
    expect(hit).toMatchObject({
      kind: 'school',
      id: 'SYNS03',
      name: 'McCaskey Campus',
      sub: 'Lancaster, PA',
      state: 'PA',
      match: 'exact',
    });
    expect(hit?.lat).toBeCloseTo(40.05, 4);
    expect(hit?.lon).toBeCloseTo(-76.29, 4);
  });

  it('marks districts', () => {
    expect(first('school district of lancaster', 'schools')?.kind).toBe('district');
  });

  it('orders groups by their best match', () => {
    expect(engine.search('lancaster').order).toEqual(['cities', 'schools', 'zips']);
    expect(engine.search('mccaskey').order[0]).toBe('schools');
  });

  it('highlights the matched part of each word', () => {
    expect(first('lanc hi', 'schools')?.highlight).toEqual([
      [0, 4],
      [10, 12],
    ]);
    expect(first("o'ne", 'schools')?.highlight).toEqual([[0, 4]]);
    // The name's "St." stands for the query's "saint".
    expect(first('saint marys', 'cities')?.highlight).toEqual([
      [0, 2],
      [4, 9],
    ]);
  });

  it('highlights typo matches', () => {
    const ranges = highlight('Lancaster High School', [{ text: 'lancastr', budget: 2 }], 2);
    expect(ranges).toEqual([[0, 9]]);
  });
});

// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { MAX_QUERY_WORDS, Tier, parseQuery } from '../query';
import { STATE_INDEX } from '../states';

const PA = STATE_INDEX.get('PA');
const NY = STATE_INDEX.get('NY');

function stateReadings(q: string) {
  return parseQuery(q)
    .readings.filter((r) => r.state >= 0)
    .map((r) => ({
      state: r.state,
      floor: r.floor,
      words: r.words.map((w) => parseQuery(q).words[w]),
    }));
}

describe('parseQuery', () => {
  it.each(['', '   ', '\t\n', '🙂', '🙂🙂 🏫', '---', '...', '\u200d'])(
    'reads %j as nothing',
    (q) => {
      const parsed = parseQuery(q);
      expect(parsed.words).toEqual([]);
      expect(parsed.readings).toEqual([]);
      expect(parsed.numeric).toBe(false);
    },
  );

  it('keeps words distinct and in order', () => {
    expect(parseQuery('Walla walla High').words).toEqual(['walla', 'high']);
  });

  it('caps the number of words', () => {
    const parsed = parseQuery('a b c d e f g h i j k l m n');
    expect(parsed.words).toHaveLength(MAX_QUERY_WORDS);
  });

  it('ignores input past the length cap', () => {
    const parsed = parseQuery(`${'x'.repeat(300)} lancaster`);
    expect(parsed.words).toEqual(['x'.repeat(40)]);
  });

  it.each([
    ['17601', true],
    ['176', true],
    ['17601-1234', true],
    ['ps 123', false],
    ['lancaster', false],
  ])('%j is numeric: %s', (q, numeric) => {
    expect(parseQuery(q).numeric).toBe(numeric);
  });

  it('drops the +4 of a ZIP+4', () => {
    expect(parseQuery('17601-1234').words).toEqual(['17601']);
  });

  it('reads a trailing state code as a state', () => {
    expect(stateReadings('lancaster pa')).toEqual([
      { state: PA, floor: Tier.exact, words: ['lancaster'] },
    ]);
  });

  it('reads a trailing state name, even of several words', () => {
    expect(stateReadings('lancaster, pennsylvania')).toEqual([
      { state: PA, floor: Tier.exact, words: ['lancaster'] },
    ]);
    expect(stateReadings('albany new york')).toContainEqual({
      state: NY,
      floor: Tier.exact,
      words: ['albany'],
    });
  });

  it('reads a state name still being typed as a prefix', () => {
    expect(stateReadings('lancaster penns')).toEqual([
      { state: PA, floor: Tier.prefix, words: ['lancaster'] },
    ]);
    expect(stateReadings('lancaster penns ')).toEqual([]);
  });

  it('reads a misspelled state name as a typo', () => {
    expect(stateReadings('lancaster pensylvania')).toEqual([
      { state: PA, floor: Tier.fuzzy, words: ['lancaster'] },
    ]);
  });

  it('reads a state only at the end', () => {
    expect(stateReadings('pa lancaster')).toEqual([]);
  });

  it('needs a real word before a state code', () => {
    expect(stateReadings('st ma')).toEqual([]);
    expect(stateReadings('ma')).toEqual([]);
  });

  it('lists a whole-query state name as a state reading with no words', () => {
    const readings = parseQuery('ohio').readings;
    expect(readings[0]?.state).toBe(-1);
    expect(readings[1]).toMatchObject({ words: [], named: true, floor: Tier.exact });
  });

  it('counts words with abbreviations spelled out', () => {
    expect(parseQuery('lancaster hs').readings[0]?.canon).toBe(3);
    expect(parseQuery('lancaster pa').readings[1]?.canon).toBe(1);
  });
});

/**
 * The query mix the search bench replays, drawn from whatever records the
 * index was built from (the SYNTHETIC set by default), so every query has
 * real targets. Most queries are keystroke prefixes, as a search box sees
 * them: "l", "la", "lan" and so on.
 */
import { STATES } from '../../src/search/states';
import type { SearchRecord } from '../../src/search/types';
import { mulberry32 } from './synthetic-records';

export const QUERY_SEED = 0x9e3779b9;

const LETTERS = ['a', 'e', 'i', 'o', 'u', 'r', 's', 't', 'l', 'n'];

type Random = () => number;

function pick<T>(random: Random, list: readonly T[]): T {
  const item = list[Math.floor(random() * list.length)];
  if (item === undefined) throw new Error('pick from an empty list');
  return item;
}

/** Every prefix of `text`, one per keystroke. */
function keystrokes(text: string): string[] {
  const out: string[] = [];
  for (let i = 1; i <= text.length; i++) out.push(text.slice(0, i));
  return out;
}

/** One or two typing mistakes in words long enough for them to be tolerated. */
function withTypos(random: Random, text: string): string {
  return text
    .split(' ')
    .map((word) => {
      if (word.length < 4) return word;
      const edits = word.length >= 8 && random() < 0.5 ? 2 : 1;
      let w = word;
      for (let e = 0; e < edits; e++) {
        const at = 1 + Math.floor(random() * (w.length - 2));
        const kind = random();
        if (kind < 0.35) w = w.slice(0, at) + (w[at + 1] ?? '') + (w[at] ?? '') + w.slice(at + 2);
        else if (kind < 0.7) w = w.slice(0, at) + w.slice(at + 1);
        else w = w.slice(0, at) + pick(random, LETTERS) + w.slice(at + 1);
      }
      return w;
    })
    .join(' ');
}

function firstWords(text: string, count: number): string {
  return text.split(' ').slice(0, count).join(' ');
}

const EDGE_CASES: readonly string[] = [
  'a',
  'e',
  's',
  'the',
  'of',
  '1',
  '0',
  '---',
  '🙂',
  '🏫 school',
  'école',
  'ñ',
  '学校',
  'São',
  '12345678901234',
  'x'.repeat(300),
  'school '.repeat(40),
  'st.',
  'p.s. 1',
  'o',
];

/**
 * About 3,000 queries in sessions: typing school names, city and state,
 * ZIP codes, abbreviations, typos, and odd input.
 */
export function benchQueries(records: readonly SearchRecord[], seed = QUERY_SEED): string[] {
  const random = mulberry32(seed);
  const schools = records.filter((r) => r.kind === 'school');
  const districts = records.filter((r) => r.kind === 'district');
  const cities = records.filter((r) => r.kind === 'city');
  const zips = records.filter((r) => r.kind === 'zip');
  const stateName = new Map(STATES.map(([code, name]) => [code, name]));
  const queries: string[] = [];

  for (let session = 0; session < 150; session++) {
    const school = pick(random, schools);
    queries.push(...keystrokes(firstWords(school.name, 3).toLowerCase()));
  }
  for (let session = 0; session < 40; session++) {
    const city = pick(random, cities);
    const text =
      random() < 0.5
        ? `${city.name} ${city.state.toLowerCase()}`
        : `${city.name}, ${stateName.get(city.state) ?? city.state}`;
    queries.push(...keystrokes(text.toLowerCase()));
  }
  for (let session = 0; session < 20; session++) {
    queries.push(...keystrokes(firstWords(pick(random, districts).name, 2).toLowerCase()));
  }
  for (let i = 0; i < 250; i++) {
    const school = pick(random, schools);
    queries.push(withTypos(random, firstWords(school.name, 2).toLowerCase()));
  }
  for (let session = 0; session < 60; session++) {
    queries.push(...keystrokes(pick(random, zips).name));
  }
  for (let i = 0; i < 120; i++) {
    const city = pick(random, cities).name.toLowerCase();
    queries.push(
      pick(random, [`${city} hs`, `${city} elem`, `st ${city.slice(0, 4)}`, `${city} ms`]),
    );
  }
  queries.push(...EDGE_CASES);
  return queries;
}

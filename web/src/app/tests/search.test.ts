import { describe, expect, it, vi } from 'vitest';

import type { IndexInfo, SearchClient, SearchHit, SearchResults } from '../../search';
import { SearchUnavailableError } from '../../search';
import {
  LIST_ROWS,
  createSearchController,
  nameParts,
  searchOptions,
  searchSections,
} from '../search';
import type { SearchOption } from '../search';

const INFO: IndexInfo = { records: 1, tokens: 1, bytes: 1, loadMs: 1, phases: {} };
const INDEX = 'https://snow.test/data/search-index.bin';

function hit(kind: SearchHit['kind'], id: string, name: string): SearchHit {
  return {
    kind,
    id,
    name,
    sub: '',
    state: 'MO',
    lat: 39,
    lon: -94.5,
    match: 'exact',
    highlight: [],
  };
}

function resultsFor(query: string): SearchResults {
  return {
    query,
    schools: [hit('school', 'A1902690', `${query} school`)],
    cities: [hit('city', '2938000', `${query} city`)],
    zips: [],
    order: ['cities', 'schools', 'zips'],
  };
}

/** A client whose searches settle when the test says. */
function fakeClient(ready: Promise<IndexInfo> = Promise.resolve(INFO)) {
  const pending = new Map<string, (results: SearchResults) => void>();
  const destroy = vi.fn();
  const client: SearchClient = {
    ready,
    search: vi.fn(
      (query: string) =>
        new Promise<SearchResults>((resolve, reject) => {
          ready.then(() => {
            pending.set(query, resolve);
          }, reject);
        }),
    ),
    destroy,
  };
  return {
    client,
    destroy,
    answer: (query: string) => pending.get(query)?.(resultsFor(query)),
  };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

describe('with no index published', () => {
  it('loads nothing and shows nothing, whatever is typed', async () => {
    const createClient = vi.fn();
    const onResults = vi.fn();
    const search = createSearchController({ indexUrl: null, onResults, createClient });
    search.warm();
    search.query('kansas city');
    expect(await search.lookup('64113')).toBeNull();
    await settle();
    expect(createClient).not.toHaveBeenCalled();
    expect(onResults.mock.calls.every(([results]) => results === null)).toBe(true);
  });
});

describe('with an index', () => {
  it('loads it on the first warm, once', async () => {
    const { client } = fakeClient();
    const createClient = vi.fn(() => Promise.resolve(client));
    const onIndexLoaded = vi.fn();
    const search = createSearchController({
      indexUrl: INDEX,
      onResults: vi.fn(),
      onIndexLoaded,
      createClient,
    });
    expect(createClient).not.toHaveBeenCalled();
    search.warm();
    search.warm();
    await settle();
    expect(createClient).toHaveBeenCalledTimes(1);
    expect(createClient).toHaveBeenCalledWith(INDEX);
    expect(onIndexLoaded).toHaveBeenCalledWith(INDEX);
  });

  it('shows only the newest text’s results', async () => {
    const { client, answer } = fakeClient();
    const onResults = vi.fn();
    const search = createSearchController({
      indexUrl: INDEX,
      onResults,
      createClient: () => Promise.resolve(client),
    });
    search.query('kan');
    search.query('kansas');
    await settle();
    answer('kan');
    answer('kansas');
    await settle();
    expect(
      onResults.mock.calls.map(([results]) => (results as SearchResults | null)?.query),
    ).toEqual(['kansas']);
    search.query('');
    expect(onResults).toHaveBeenLastCalledWith(null);
  });

  it('goes quiet for good when the index cannot load', async () => {
    const failure = new SearchUnavailableError('no index');
    const ready = Promise.reject(failure);
    ready.catch(() => undefined);
    const { client } = fakeClient(ready);
    const onResults = vi.fn();
    const search = createSearchController({
      indexUrl: INDEX,
      onResults,
      createClient: () => Promise.resolve(client),
    });
    search.query('kansas');
    await settle();
    expect(onResults).toHaveBeenLastCalledWith(null);
    onResults.mockClear();
    search.query('kansas city');
    expect(onResults).toHaveBeenLastCalledWith(null);
    expect(await search.lookup('64113')).toBeNull();
  });

  it('goes quiet when the search code cannot load', async () => {
    const onResults = vi.fn();
    const search = createSearchController({
      indexUrl: INDEX,
      onResults,
      createClient: () => Promise.reject(new Error('chunk failed')),
    });
    search.warm();
    await settle();
    search.query('kansas');
    expect(onResults).toHaveBeenLastCalledWith(null);
  });

  it('stops the worker when destroyed', async () => {
    const { client, destroy } = fakeClient();
    const search = createSearchController({
      indexUrl: INDEX,
      onResults: vi.fn(),
      createClient: () => Promise.resolve(client),
    });
    search.warm();
    await settle();
    search.destroy();
    expect(destroy).toHaveBeenCalled();
  });
});

describe('laying out results', () => {
  it('numbers options in the suggested group order, one section per kind', () => {
    const options = searchOptions(resultsFor('kansas'), 'list');
    expect(options.map((option) => [option.id, option.section])).toEqual([
      ['list-0', 'city'],
      ['list-1', 'school'],
    ]);
    expect(
      searchSections(options).map((section) => [
        section.kind,
        section.start,
        section.options.map((option) => option.id),
      ]),
    ).toEqual([
      ['city', 0, ['list-0']],
      ['school', 1, ['list-1']],
    ]);
  });

  /** Search hits named `names`, of one kind, a kilometre or more apart. */
  const hits = (kind: SearchHit['kind'], names: readonly string[]): SearchHit[] =>
    names.map((name, i) => ({
      ...hit(kind, `${kind}-${String(i)}`, name),
      sub: 'Kansas City, MO',
      lat: 39 + i / 50,
    }));

  it('lists districts and schools apart, in the order of their best hit', () => {
    const schools = [
      ...hits('district', ['KANSAS CITY 33']),
      ...hits('school', ['NORTH KANSAS CITY HIGH']),
      ...hits('district', ['NORTH KANSAS CITY 74']),
    ];
    const options = searchOptions(
      { query: 'kansas city', schools, cities: [], zips: [], order: ['cities', 'schools', 'zips'] },
      'list',
    );
    expect(options.map((option) => [option.section, option.name])).toEqual([
      ['district', 'Kansas City 33'],
      ['district', 'North Kansas City 74'],
      ['school', 'North Kansas City High'],
    ]);
    expect(options.map((option) => option.id)).toEqual(['list-0', 'list-1', 'list-2']);
    expect(searchSections(options).map((section) => section.start)).toEqual([0, 2]);
  });

  it('shares LIST_ROWS rows out: some of every kind, then each kind’s share, then the rest', () => {
    const many = (kind: SearchHit['kind']): SearchHit[] =>
      hits(
        kind,
        Array.from({ length: 16 }, (_, i) => `Kansas City ${String(i)}`),
      );
    const count = (options: readonly SearchOption[]): Record<string, number> =>
      Object.fromEntries(searchSections(options).map((s) => [s.kind, s.options.length]));
    const all = searchOptions(
      {
        query: 'kansas city',
        schools: [...many('district'), ...many('school')],
        cities: many('city'),
        zips: [],
        order: ['cities', 'schools', 'zips'],
      },
      'list',
    );
    expect(all).toHaveLength(LIST_ROWS);
    expect(count(all)).toEqual({ city: 4, district: 3, school: 5 });
    // Three places leave a row, which goes to the districts after them.
    const few = searchOptions(
      {
        query: 'kansas city',
        schools: [...many('district'), ...many('school')],
        cities: many('city').slice(0, 3),
        zips: [],
        order: ['cities', 'schools', 'zips'],
      },
      'list',
    );
    expect(count(few)).toEqual({ city: 3, district: 4, school: 5 });
    // Schools alone take up to eight rows.
    const alone = searchOptions(
      { query: 'kansas city', schools: many('school'), cities: [], zips: [], order: ['schools'] },
      'list',
    );
    expect(count(alone)).toEqual({ school: 8 });
    // Every kind that has hits shows some, whatever comes first.
    const zips = searchOptions(
      {
        query: '6',
        schools: [...many('district'), ...many('school')],
        cities: many('city'),
        zips: many('zip'),
        order: ['zips', 'schools', 'cities'],
      },
      'list',
    );
    expect(count(zips)).toEqual({ zip: 5, district: 3, school: 2, city: 2 });
    expect(zips).toHaveLength(LIST_ROWS);
  });

  it('lists a school the directory has twice at one address once, and keeps namesakes apart', () => {
    const academy = (id: string, lat: number): SearchHit => ({
      ...hit('school', id, 'KANSAS CITY ACADEMY'),
      sub: 'Kansas City, MO',
      lat,
    });
    const options = searchOptions(
      {
        query: 'kansas city academy',
        // Two ids, ten metres apart, as the directory has them; then one across town.
        schools: [academy('A9103777', 38.9837), academy('A2392120', 38.9836), academy('X', 39.1)],
        cities: [],
        zips: [],
        order: ['schools'],
      },
      'list',
    );
    expect(options.map((option) => option.hit.id)).toEqual(['A9103777', 'X']);
  });

  it('shows names written in capitals in title case, matched where the raw name matched', () => {
    const pembroke: SearchHit = {
      ...hit('school', 'A1902690', 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS'),
      sub: 'Kansas City, MO',
      highlight: [[4, 12]],
    };
    const [option] = searchOptions(
      { query: 'pembroke', schools: [pembroke], cities: [], zips: [], order: ['schools'] },
      'list',
    );
    expect(option?.name).toBe('The Pembroke Hill School - Wornall Campus');
    expect(option?.sub).toBe('Kansas City, MO');
    // The hit keeps its raw name, for search and for the link.
    expect(option?.hit.name).toBe('THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS');
    expect(option?.parts.filter((part) => part.match).map((part) => part.text)).toEqual([
      'Pembroke',
    ]);
  });

  it('spells out a school’s shortenings and bolds the words a matched one stands for', () => {
    const ross: SearchHit = {
      ...hit('school', '421866004476', 'Ross El Sch'),
      state: 'PA',
      highlight: [
        [0, 4],
        [8, 11],
      ],
    };
    const [option] = searchOptions(
      { query: 'ross school', schools: [ross], cities: [], zips: [], order: ['schools'] },
      'list',
    );
    expect(option?.name).toBe('Ross Elementary School');
    expect(option?.parts).toEqual([
      { text: 'Ross', match: true },
      { text: ' Elementary ', match: false },
      { text: 'School', match: true },
    ]);
  });

  it('keeps Mississippi’s MS, and a place’s words as written', () => {
    const blind: SearchHit = {
      ...hit('school', '280019401239', 'NORTHEAST MS REGIONAL ALTERNATIVE'),
      state: 'MS',
    };
    const city: SearchHit = { ...hit('city', '2803500', 'EL PASO'), state: 'MS' };
    const options = searchOptions(
      { query: 'ms', schools: [blind], cities: [city], zips: [], order: ['schools', 'cities'] },
      'list',
    );
    expect(options.map((option) => option.name)).toEqual([
      'Northeast MS Regional Alternative',
      'El Paso',
    ]);
  });

  it('cuts a name into matched and unmatched runs', () => {
    expect(
      nameParts({
        name: 'North Kansas City',
        highlight: [
          [6, 12],
          [13, 17],
        ],
      }),
    ).toEqual([
      { text: 'North ', match: false },
      { text: 'Kansas', match: true },
      { text: ' ', match: false },
      { text: 'City', match: true },
    ]);
    expect(nameParts({ name: 'Kansas', highlight: [] })).toEqual([
      { text: 'Kansas', match: false },
    ]);
    // Overlapping and out-of-range ranges never repeat or lose a letter.
    expect(
      nameParts({
        name: 'Kansas',
        highlight: [
          [3, 9],
          [0, 4],
        ],
      })
        .map((part) => part.text)
        .join(''),
    ).toBe('Kansas');
  });
});

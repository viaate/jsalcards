import { describe, expect, it, vi } from 'vitest';

import type { IndexInfo, SearchClient, SearchHit, SearchResults } from '../../search';
import { SearchUnavailableError } from '../../search';
import { createSearchController, nameParts, searchOptions } from '../search';

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
  it('numbers options in the suggested group order and marks where groups start', () => {
    const options = searchOptions(resultsFor('kansas'), 'list');
    expect(options.map((option) => [option.id, option.group, option.startsGroup])).toEqual([
      ['list-0', 'cities', false],
      ['list-1', 'schools', true],
    ]);
  });

  it('shows names written in capitals in title case, matched where the raw name matched', () => {
    const pembroke: SearchHit = {
      ...hit('school', 'A1902690', 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS'),
      sub: 'KANSAS CITY 33',
      highlight: [[4, 12]],
    };
    const [option] = searchOptions(
      { query: 'pembroke', schools: [pembroke], cities: [], zips: [], order: ['schools'] },
      'list',
    );
    expect(option?.name).toBe('The Pembroke Hill School - Wornall Campus');
    expect(option?.sub).toBe('Kansas City 33');
    // The hit keeps its raw name, for search and for the link.
    expect(option?.hit.name).toBe('THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS');
    const parts = nameParts({ name: option?.name ?? '', highlight: pembroke.highlight });
    expect(parts.filter((part) => part.match).map((part) => part.text)).toEqual(['Pembroke']);
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

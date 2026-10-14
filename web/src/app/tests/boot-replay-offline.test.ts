/**
 * A link to a past day when replay mode's code cannot load (offline, a deploy
 * in flight): live comes on, and the address drops the day.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createDirectory, parsePoints } from '../../data/directory';
import { createDataFiles } from '../../data/files';
import {
  jsonResponse,
  testClosings,
  testDay,
  testMeta,
  testPoints,
} from '../../data/tests/builders';
import type { StatusCounts } from '../../data/closings';
import type { Basemap } from '../../map/basemap';
import type { Glow } from '../../map/glow-mount';
import { createUrlStore } from '../../state/url-store';
import { boot } from '../boot';

vi.mock('../replay', () => {
  throw new Error('offline');
});

const SCHOOLS = [{ id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: -1 }];
const META = testMeta(SCHOOLS);
const POINTS = parsePoints(testPoints(SCHOOLS, 0), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
/** SYNTHETIC: live closes the one school today. */
const LIVE = testClosings('2026-01-12T12:42:00Z', META, [testDay('2026-01-12', [[0, 0]])]);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  history.replaceState(null, '', '/');
});

describe('a link to a past day whose code cannot load', () => {
  it('opens live, and the address drops the day', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-01-12T18:00:00Z'));
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse(LIVE))),
    );
    Object.defineProperty(document, 'fonts', {
      value: { ready: Promise.resolve() },
      configurable: true,
    });
    history.replaceState(null, '', '/?replay=2026-01-05&school=010000500870');
    const counts: (StatusCounts | null)[] = [];
    const glow = {
      light: () => undefined,
      dust: () => undefined,
      showSchools: () => undefined,
      select: () => undefined,
      remove: () => undefined,
      lit: null,
      specks: null,
    } as unknown as Glow;
    const controller = new AbortController();
    boot({
      links: createUrlStore(),
      map: Promise.resolve({ moved: false, showSchools: () => undefined } as unknown as Basemap),
      glow: Promise.resolve(glow),
      signal: controller.signal,
      show: () => undefined,
      listId: 'list',
      onResults: () => undefined,
      onCounts: (next) => counts.push(next),
      data: {
        files: createDataFiles(
          ['live/closings.json', 'schools/meta.json', 'schools/points.bin'],
          'https://snow.test/data/',
        ),
        directories: () => Promise.resolve({ get: () => Promise.resolve(DIRECTORY) }),
      },
    });
    await vi.waitFor(
      () => {
        expect(counts.at(-1)).toEqual([1, 0, 0, 0]);
      },
      { timeout: 4_000 },
    );
    expect(location.search).toBe('?school=010000500870');
    controller.abort();
  });
});

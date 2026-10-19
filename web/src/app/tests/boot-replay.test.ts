/**
 * Replay mode as boot wires it: live's counts and time never land over a
 * replay, a link's day is held for from the start, and one that cannot be
 * shown leaves live and the address as live.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LitSchools, StatusCounts } from '../../data/closings';
import { createDirectory, parsePoints } from '../../data/directory';
import type { DirectorySource } from '../../data/directory';
import { createDataFiles } from '../../data/files';
import {
  jsonResponse,
  testClosings,
  testDay,
  testMeta,
  testPoints,
  testReplay,
} from '../../data/tests/builders';
import type { Basemap } from '../../map/basemap';
import type { Glow } from '../../map/glow-mount';
import { createUrlStore } from '../../state/url-store';
import type { LocalDate } from '../../types/generated';
import { boot } from '../boot';
import type { AppData } from '../data';

const ROOT = 'https://snow.test/data/';
const WAIT = { timeout: 4_000 };
const SCHOOLS = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: -1 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: -1 },
  { id: '010000500872', name: 'Third', lon: -86.4, lat: 33.9, district: -1 },
];
const META = testMeta(SCHOOLS);
const POINTS = parsePoints(testPoints(SCHOOLS, 0), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
/** SYNTHETIC: live closes the first school today; the replay day had the other two remote. */
const LIVE = testClosings('2026-01-12T12:42:00Z', META, [testDay('2026-01-12', [[0, 0]])]);
const REPLAY = testReplay('2026-01-05', META, [
  [1, 2, 0],
  [2, 2, 0],
]);
const FILES = [
  'live/closings.json',
  'replays/2026-01-05.0123456789.json',
  'schools/meta.json',
  'schools/points.bin',
];

function appData(): AppData {
  const source: DirectorySource = { get: () => Promise.resolve(DIRECTORY) };
  return { files: createDataFiles(FILES, ROOT), directories: () => Promise.resolve(source) };
}

let fontsReady: () => void = () => undefined;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-01-12T18:00:00Z'));
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(jsonResponse(url.includes('/replays/') ? REPLAY : LIVE)),
    ),
  );
  // The page's face, which counts wait for: in when the test says.
  const ready = new Promise<void>((resolve) => {
    fontsReady = resolve;
  });
  Object.defineProperty(document, 'fonts', { value: { ready }, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  history.replaceState(null, '', '/');
});

function start() {
  const counts: (StatusCounts | null)[] = [];
  const updated: (string | null)[] = [];
  const days: (LocalDate | null)[] = [];
  const painted: LitSchools[] = [];
  const glow = {
    light: (lit: LitSchools) => painted.push(lit),
    dust: () => undefined,
    showSchools: () => undefined,
    select: () => undefined,
    remove: () => undefined,
    lit: null,
    specks: null,
  } as unknown as Glow;
  const map = { moved: false, showSchools: () => undefined } as unknown as Basemap;
  const controller = new AbortController();
  const services = boot({
    links: createUrlStore(),
    map: Promise.resolve(map),
    glow: Promise.resolve(glow),
    signal: controller.signal,
    show: () => undefined,
    listId: 'list',
    onResults: () => undefined,
    onCounts: (next) => counts.push(next),
    onUpdated: (at) => updated.push(at),
    onReplay: (replay) => days.push(replay?.day ?? null),
    data: appData(),
  });
  return { services, counts, updated, days, painted, controller };
}

describe('replay mode, as boot runs it', () => {
  it("delivers no live counts heard before a replay came on, only the replay's", async () => {
    const { services, counts, updated, days, controller } = start();
    // Live's counts are heard, and wait for the face.
    await vi.waitFor(() => {
      expect(updated).toEqual(['2026-01-12T12:42:00Z']);
    }, WAIT);
    services.replay('2026-01-05');
    await vi.waitFor(() => {
      expect(days).toEqual(['2026-01-05']);
    }, WAIT);
    fontsReady();
    await vi.waitFor(() => {
      expect(counts).toEqual([[0, 0, 2, 0]]);
    }, WAIT);
    expect(updated).toEqual(['2026-01-12T12:42:00Z', null]);
    expect(location.search).toBe('?replay=2026-01-05');

    // Back to live: live's own counts and time again.
    services.replay(null);
    await vi.waitFor(() => {
      expect(counts).toEqual([
        [0, 0, 2, 0],
        [1, 0, 0, 0],
      ]);
    }, WAIT);
    expect(days).toEqual(['2026-01-05', null]);
    expect(updated.at(-1)).toBe('2026-01-12T12:42:00Z');
    expect(location.search).toBe('');
    controller.abort();
  });

  it('reads a day ahead of a press with nothing on screen changed, and the press shows it', async () => {
    fontsReady();
    const { services, days, updated, controller } = start();
    await vi.waitFor(() => {
      expect(updated).toEqual(['2026-01-12T12:42:00Z']);
    }, WAIT);
    services.replay('2026-01-05', true);
    await vi.waitFor(() => {
      expect(
        vi.mocked(fetch).mock.calls.some(([url]) => (url as string).includes('/replays/')),
      ).toBe(true);
    }, WAIT);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(days).toEqual([]);
    expect(location.search).toBe('');
    const reads = vi.mocked(fetch).mock.calls.length;
    services.replay('2026-01-05');
    await vi.waitFor(() => {
      expect(days).toEqual(['2026-01-05']);
    }, WAIT);
    // The day was read once.
    expect(vi.mocked(fetch).mock.calls.length).toBe(reads);
    controller.abort();
  });

  it('holds live from the start for a link to a past day: live never paints first', async () => {
    history.replaceState(null, '', '/?replay=2026-01-05');
    fontsReady();
    const { counts, days, painted, controller } = start();
    await vi.waitFor(() => {
      expect(days).toEqual(['2026-01-05']);
    }, WAIT);
    await vi.waitFor(() => {
      expect(counts).toEqual([[0, 0, 2, 0]]);
    }, WAIT);
    // Every paint so far is the replay's: its two schools, never live's one.
    expect(painted.length).toBeGreaterThan(0);
    for (const lit of painted) expect([...lit.schools]).toEqual([1, 2]);
    controller.abort();
  });

  it.each(['1999-01-01', '2026-01-12', '2026-01-13', '2026-1-5'])(
    'opens live for a link to %s, and the address drops it',
    async (day) => {
      history.replaceState(null, '', `/?replay=${day}&school=010000500870`);
      fontsReady();
      const { counts, days, controller } = start();
      // Live's counts, and none of the day's. A null may come first, as the link's day is let go
      // before live's first file is lit: no counts, which is what the page shows until then.
      await vi.waitFor(() => {
        expect(counts.filter((next) => next !== null)).toEqual([[1, 0, 0, 0]]);
        expect(counts.at(-1)).toEqual([1, 0, 0, 0]);
      }, WAIT);
      expect(days).toEqual([]);
      await vi.waitFor(() => {
        expect(location.search).toBe('?school=010000500870');
      }, WAIT);
      controller.abort();
    },
  );

  it('follows Back from a link to a past day while replay mode still loads: live, and the address with it', async () => {
    history.replaceState(null, '', '/?replay=2026-01-05&school=010000500870');
    fontsReady();
    const { counts, days, controller } = start();
    // Back at once, before replay mode's code is in: the entry before, without the day.
    history.replaceState(null, '', '/?school=010000500870');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await vi.waitFor(() => {
      expect(location.search).toBe('?school=010000500870');
    }, WAIT);
    await vi.waitFor(() => {
      expect(counts.at(-1)).toEqual([1, 0, 0, 0]);
    }, WAIT);
    // The day never came on, and the address never took it back.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(days).toEqual([]);
    expect(location.search).toBe('?school=010000500870');
    controller.abort();
  });
});

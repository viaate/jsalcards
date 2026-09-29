import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LitSchools, StatusCounts } from '../closings';
import { createDirectory, parsePoints } from '../directory';
import type { Directory } from '../directory';
import { createDataFiles } from '../files';
import { LIVE_POLL_MS, closingsUrl, startLive } from '../live';
import type { LiveHost } from '../live';
import { jsonResponse, testClosings, testDay, testMeta, testPoints } from './builders';
import type { TestSchool } from './builders';

const ROOT = 'https://snow.test/data/';
const SCHOOLS: TestSchool[] = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: 0 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: 0 },
  { id: 'A1902690', name: 'Third', lon: -94.593001, lat: 39.03606, district: -1 },
];
const META = testMeta(SCHOOLS, ['0100005']);
const POINTS = parsePoints(testPoints(SCHOOLS, 1), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
const NOON = new Date('2026-01-12T18:00:00Z');

class FakeDocument extends EventTarget {
  visibilityState: DocumentVisibilityState = 'visible';
}

function fakeHost(): LiveHost & { document: FakeDocument } {
  return {
    document: new FakeDocument(),
    setInterval: (handler, timeout) => setInterval(handler, timeout) as unknown as number,
    clearInterval: (id) => {
      clearInterval(id);
    },
  };
}

function setup(answer: () => Promise<Response>, shipped = ['live/closings.json']) {
  const fetchImpl = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(answer);
  const directory = vi.fn(() => Promise.resolve<Directory | null>(DIRECTORY));
  const lights: LitSchools[] = [];
  const shown: (string | null)[] = [];
  const counts: (StatusCounts | null)[] = [];
  const host = fakeHost();
  let now = NOON;
  const live = startLive({
    files: createDataFiles(shipped, ROOT),
    directory,
    onLight: (lit) => lights.push(lit),
    onShown: (generatedAt) => shown.push(generatedAt),
    onCounts: (next) => counts.push(next),
    fetch: fetchImpl,
    now: () => now,
    clock: () => 1000,
    host,
  });
  return {
    live,
    fetchImpl,
    directory,
    lights,
    shown,
    counts,
    host,
    setNow: (next: Date) => {
      now = next;
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOON);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('a build without live/closings.json', () => {
  it('never asks for it, and lights nothing', async () => {
    const { live, fetchImpl, lights } = setup(() => Promise.resolve(jsonResponse({})), []);
    await live.refresh();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 3);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(lights).toEqual([]);
    expect(closingsUrl(createDataFiles([], ROOT))).toBeNull();
    live.stop();
  });
});

describe('a missing or broken file', () => {
  it('shows nothing and says nothing', async () => {
    const warn = vi.spyOn(console, 'warn');
    const error = vi.spyOn(console, 'error');
    for (const answer of [
      () => Promise.resolve(jsonResponse({ missing: true }, 404)),
      () => Promise.reject(new TypeError('Failed to fetch')),
      () => Promise.resolve(jsonResponse({ schema_version: 1 })),
    ]) {
      const { live, lights, directory, shown, counts } = setup(answer);
      await live.refresh();
      expect(lights).toEqual([]);
      expect(shown).toEqual([]);
      expect(counts).toEqual([]);
      expect(directory).not.toHaveBeenCalled();
      expect(live.closings).toBeNull();
      live.stop();
    }
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    warn.mockRestore();
    error.mockRestore();
  });
});

describe('a file with schools today', () => {
  const file = testClosings('2026-01-12T12:42:00Z', META, [
    testDay('2026-01-12', [
      [0, 0],
      [2, 1],
    ]),
  ]);

  it('reads it past the HTTP cache and lights its schools', async () => {
    const { live, lights, fetchImpl } = setup(() => Promise.resolve(jsonResponse(file)));
    await live.refresh();
    expect(fetchImpl.mock.calls[0]).toEqual([`${ROOT}live/closings.json`, { cache: 'no-cache' }]);
    expect(lights).toHaveLength(1);
    expect([...(lights[0]?.schools ?? [])]).toEqual([0, 2]);
    expect(lights[0]?.bornAt).toBeUndefined();
    live.stop();
  });

  it('keeps what it shows when a later read fails', async () => {
    let answer = (): Promise<Response> => Promise.resolve(jsonResponse(file));
    const { live, lights } = setup(() => answer());
    await live.refresh();
    answer = () => Promise.reject(new TypeError('offline'));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(lights).toHaveLength(1);
    expect(live.closings).toEqual(file);
    live.stop();
  });

  it('pulses the schools a newer file adds, and goes dark when the day is over', async () => {
    let current: unknown = file;
    const { live, lights, setNow } = setup(() => Promise.resolve(jsonResponse(current)));
    await live.refresh();
    current = testClosings('2026-01-12T12:57:00Z', META, [
      testDay('2026-01-12', [
        [0, 0],
        [1, 2],
        [2, 1],
      ]),
    ]);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(lights).toHaveLength(2);
    expect(lights[1]?.bornAt === undefined ? null : [...lights[1].bornAt]).toEqual([
      Number.NaN,
      1000,
      Number.NaN,
    ]);

    // Overnight, the same file lights nothing.
    setNow(new Date('2026-01-13T05:00:00Z'));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(lights).toHaveLength(3);
    expect(lights[2]?.schools.size).toBe(0);
    live.stop();
  });

  it('reads nothing while hidden, and catches up when shown', async () => {
    const { live, fetchImpl, host } = setup(() => Promise.resolve(jsonResponse(file)));
    await live.refresh();
    const reads = fetchImpl.mock.calls.length;
    host.document.visibilityState = 'hidden';
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 2);
    expect(fetchImpl.mock.calls.length).toBe(reads);
    host.document.visibilityState = 'visible';
    host.document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl.mock.calls.length).toBe(reads + 1);
    live.stop();
  });

  it('lights nothing when the directory the file names cannot be had', async () => {
    const { live, lights, directory, shown } = setup(() => Promise.resolve(jsonResponse(file)));
    directory.mockResolvedValue(null);
    await live.refresh();
    expect(lights).toEqual([]);
    // Nothing from the file is shown, so no time is given for it.
    expect(shown).toEqual([]);
    live.stop();
  });

  it('gives the time of the file shown, once for each file', async () => {
    let current: unknown = file;
    const { live, shown, directory } = setup(() => Promise.resolve(jsonResponse(current)));
    await live.refresh();
    expect(shown).toEqual(['2026-01-12T12:42:00Z']);
    // The same file read again, and a failed read, change nothing.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    current = { broken: true };
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(shown).toEqual(['2026-01-12T12:42:00Z']);
    // A newer file whose directory cannot be had takes the time away with its schools.
    current = testClosings('2026-01-12T12:57:00Z', META, file.days);
    directory.mockResolvedValue(null);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(shown).toEqual(['2026-01-12T12:42:00Z', null]);
    live.stop();
  });

  it('gives the time of a file with no schools today', async () => {
    const quiet = testClosings('2026-01-12T12:42:00Z', META, []);
    const { live, lights, shown, directory, counts } = setup(() =>
      Promise.resolve(jsonResponse(quiet)),
    );
    await live.refresh();
    expect(lights).toEqual([]);
    expect(directory).not.toHaveBeenCalled();
    expect(shown).toEqual(['2026-01-12T12:42:00Z']);
    // No school is lit, so the legend is given no count.
    expect(counts).toEqual([]);
    live.stop();
  });

  it('counts the schools it lights in each status, once for each change', async () => {
    let current: unknown = file;
    const { live, counts, setNow, directory } = setup(() => Promise.resolve(jsonResponse(current)));
    await live.refresh();
    expect(counts).toEqual([[1, 1, 0, 0]]);
    // The same counts from a newer file say nothing new.
    current = testClosings('2026-01-12T12:50:00Z', META, file.days);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(counts).toEqual([[1, 1, 0, 0]]);
    // A school goes remote.
    current = testClosings('2026-01-12T12:57:00Z', META, [
      testDay('2026-01-12', [
        [0, 0],
        [1, 2],
        [2, 1],
      ]),
    ]);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(counts).toEqual([
      [1, 1, 0, 0],
      [1, 1, 1, 0],
    ]);
    // Overnight nothing is lit, and no count is given.
    setNow(new Date('2026-01-13T05:00:00Z'));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(counts.at(-1)).toBeNull();
    // Back in the day, a file whose directory cannot be had lights nothing, and counts nothing.
    setNow(NOON);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(counts.at(-1)).toEqual([1, 1, 1, 0]);
    current = testClosings('2026-01-12T13:12:00Z', META, file.days);
    directory.mockResolvedValue(null);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(counts.at(-1)).toBeNull();
    live.stop();
  });
});

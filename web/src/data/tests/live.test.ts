import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { LitSchools, StatusCounts } from '../closings';
import { createDirectory, parsePoints } from '../directory';
import type { Directory } from '../directory';
import { createDataFiles } from '../files';
import {
  LIVE_POLL_MS,
  LIVE_READ_TIMEOUT_MS,
  closingsReader,
  closingsUrl,
  newerClosings,
  pollWhileVisible,
  startLive,
} from '../live';
import type { LiveHost } from '../live';
import type { ClosingsFile } from '../../types/generated';
import { WAKE_CHECK_MS } from '../../state/wake';
import { updateState } from '../../state/freshness';
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
    expect(fetchImpl.mock.calls[0]).toEqual([
      `${ROOT}live/closings.json`,
      { cache: 'no-cache', signal: expect.any(AbortSignal) as unknown },
    ]);
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

describe('only a newer file', () => {
  const day = testDay('2026-01-12', [
    [0, 0],
    [2, 1],
  ]);
  const first = testClosings('2026-01-12T12:42:00Z', META, [day]);
  const later = testClosings('2026-01-12T12:57:00Z', META, [
    testDay('2026-01-12', [
      [0, 0],
      [1, 2],
      [2, 1],
    ]),
  ]);

  it('takes a later generated_at, and keeps the file shown for an earlier or equal one', () => {
    expect(newerClosings(null, first)).toBe(first);
    expect(newerClosings(first, later)).toBe(later);
    expect(newerClosings(later, first)).toBe(later);
    const again = testClosings('2026-01-12T12:57:00Z', META, []);
    expect(newerClosings(later, again)).toBe(later);
    expect(newerClosings(later, null)).toBe(later);
    expect(newerClosings(null, null)).toBeNull();
    // A second later, a day later: the fixed form compares as text, as time does.
    const second = testClosings('2026-01-12T12:57:01Z', META, []);
    expect(newerClosings(later, second)).toBe(second);
    const nextDay = testClosings('2026-01-13T00:00:00Z', META, []);
    expect(newerClosings(second, nextDay)).toBe(nextDay);
  });

  it('ignores an older or equal file read after a newer one, and lights what the newer one says', async () => {
    let current: unknown = later;
    const { live, lights, shown } = setup(() => Promise.resolve(jsonResponse(current)));
    await live.refresh();
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1, 2]);
    // An edge or a cache that has not caught up serves the older file: nothing changes.
    current = first;
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    // And a copy with the same time but other rows is not taken either.
    current = testClosings('2026-01-12T12:57:00Z', META, [day]);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(lights).toHaveLength(1);
    expect(shown).toEqual(['2026-01-12T12:57:00Z']);
    expect(live.closings?.generated_at).toBe('2026-01-12T12:57:00Z');
    expect(live.closings?.days[0]?.gaps).toHaveLength(3);
    // A blank file published after it is newer, so it is taken, and the map goes dark.
    current = testClosings('2026-01-12T13:02:00Z', META, []);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(lights).toHaveLength(2);
    expect(lights[1]?.schools.size).toBe(0);
    expect(shown).toEqual(['2026-01-12T12:57:00Z', '2026-01-12T13:02:00Z']);
    live.stop();
  });

  it('reads the file every minute by default', async () => {
    expect(LIVE_POLL_MS).toBe(60_000);
    const { live, fetchImpl } = setup(() => Promise.resolve(jsonResponse(first)));
    await live.refresh();
    const reads = fetchImpl.mock.calls.length;
    await vi.advanceTimersByTimeAsync(59_000);
    expect(fetchImpl.mock.calls.length).toBe(reads);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fetchImpl.mock.calls.length).toBe(reads + 1);
    await vi.advanceTimersByTimeAsync(60_000 * 3);
    expect(fetchImpl.mock.calls.length).toBe(reads + 4);
    live.stop();
  });
});

describe('polling while the page is seen', () => {
  it('reads every period while visible, never while hidden, and at once when seen again', async () => {
    const host = fakeHost();
    const read = vi.fn();
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host });
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(read).toHaveBeenCalledTimes(1);
    host.document.visibilityState = 'hidden';
    host.document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 5);
    expect(read).toHaveBeenCalledTimes(1);
    // Seen again a period or more after the last read: read now.
    host.document.visibilityState = 'visible';
    host.document.dispatchEvent(new Event('visibilitychange'));
    expect(read).toHaveBeenCalledTimes(2);
    // Hidden and seen again within a period: the next tick reads.
    host.document.visibilityState = 'hidden';
    host.document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10_000);
    host.document.visibilityState = 'visible';
    host.document.dispatchEvent(new Event('visibilitychange'));
    expect(read).toHaveBeenCalledTimes(2);
    stop();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 3);
    host.document.dispatchEvent(new Event('visibilitychange'));
    expect(read).toHaveBeenCalledTimes(2);
  });
});

describe('a poll\u2019s period', () => {
  it('starts again from a read made on show, so the next comes a full period later', async () => {
    const host = fakeHost();
    const read = vi.fn();
    const start = performance.now();
    const times: number[] = [];
    read.mockImplementation(() => times.push(performance.now() - start));
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host });
    await vi.advanceTimersByTimeAsync(1000);
    host.document.visibilityState = 'hidden';
    host.document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(66_000);
    host.document.visibilityState = 'visible';
    host.document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(3 * LIVE_POLL_MS);
    expect(times).toEqual([67_000, 127_000, 187_000, 247_000]);
    stop();
  });

  /** A pace whose reads the test makes, as another poll's reads through the shared reader. */
  function fakePace() {
    const listeners = new Set<() => void>();
    return {
      listeners,
      onRead: (listener: () => void) => {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      renew: () => undefined,
      /** Another poll's read goes out. */
      read: () => {
        for (const listener of [...listeners]) listener();
      },
    };
  }

  it('runs its own work with each read that goes out through its pace, whoever made it, and starts its period again', async () => {
    const host = fakeHost();
    const read = vi.fn();
    const pace = fakePace();
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host, pace });
    await vi.advanceTimersByTimeAsync(40_000);
    // Another made a read 40 s in: this poll's own work runs with it, so its view is worked out
    // again against the time and its own files read when due, and its next call comes a full
    // period after it.
    pace.read();
    await vi.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS - 1);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(read).toHaveBeenCalledTimes(2);
    // Another read every half period, all hour: this poll still runs at every one of them.
    for (let i = 0; i < 120; i += 1) {
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS / 2);
      pace.read();
    }
    await vi.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(122);
    // Hidden: another's read starts the period again but runs nothing.
    host.document.visibilityState = 'hidden';
    pace.read();
    await vi.advanceTimersByTimeAsync(0);
    expect(read).toHaveBeenCalledTimes(122);
    host.document.visibilityState = 'visible';
    // Stopped while another's read is on its way: nothing more runs.
    pace.read();
    stop();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 2);
    expect(read).toHaveBeenCalledTimes(122);
    expect(pace.listeners.size).toBe(0);
  });

  it('runs once for a read it made itself, through its pace', async () => {
    const host = fakeHost();
    const pace = fakePace();
    const read = vi.fn(() => {
      pace.read();
    });
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host, pace });
    await vi.advanceTimersByTimeAsync(3 * LIVE_POLL_MS);
    expect(read).toHaveBeenCalledTimes(3);
    stop();
  });

  it('never runs its work inside the call of the one whose read went out', () => {
    const host = fakeHost();
    const read = vi.fn();
    const pace = fakePace();
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host, pace });
    pace.read();
    // The asker may be part way through its own work (startLive sets what it is running only
    // once its read has begun): the poll's own work comes after.
    expect(read).not.toHaveBeenCalled();
    stop();
  });
});

describe('the page\u2019s one reader of the closings file', () => {
  const at = (generatedAt: string, rows: Parameters<typeof testDay>[1] = []) =>
    testClosings(generatedAt, META, rows.length === 0 ? [] : [testDay('2026-01-12', rows)]);
  const AT_42 = at('2026-01-12T12:42:00Z', [[0, 0]]);
  const AT_47 = at('2026-01-12T12:47:00Z', [
    [0, 0],
    [1, 1],
  ]);
  const BLANK = at('2026-01-12T12:52:00Z');

  it('is one for the page\u2019s files, and holds the newest file any read took', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const reader = closingsReader(files);
    expect(closingsReader(files)).toBe(reader);
    // Another page's files, another reader.
    expect(closingsReader(createDataFiles(['live/closings.json'], ROOT))).not.toBe(reader);
    const answers = [AT_47, AT_42, BLANK, AT_47];
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(answers.shift() ?? null)));
    const heard: string[] = [];
    reader.subscribe((file) => heard.push(file.generated_at));
    expect(reader.current).toBeNull();
    expect((await reader.read({ fetch: fetchImpl }))?.generated_at).toBe(AT_47.generated_at);
    // An older copy is not taken, whoever reads it.
    expect((await reader.read({ fetch: fetchImpl, force: true }))?.generated_at).toBe(
      AT_47.generated_at,
    );
    expect((await reader.read({ fetch: fetchImpl, force: true }))?.generated_at).toBe(
      BLANK.generated_at,
    );
    expect((await reader.read({ fetch: fetchImpl, force: true }))?.generated_at).toBe(
      BLANK.generated_at,
    );
    expect(reader.current?.generated_at).toBe(BLANK.generated_at);
    expect(heard).toEqual([AT_47.generated_at, BLANK.generated_at]);
    expect(fetchImpl).toHaveBeenCalledTimes(4);
  });

  it('reads once for readers that ask together, or within most of a poll of each other', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const reader = closingsReader(files);
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(AT_42)));
    await Promise.all([reader.read({ fetch: fetchImpl }), reader.read({ fetch: fetchImpl })]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 0.9 - 1);
    expect((await reader.read({ fetch: fetchImpl }))?.generated_at).toBe(AT_42.generated_at);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await reader.read({ fetch: fetchImpl });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // The worker said it holds a newer copy: read it, however recent the last read.
    await reader.read({ fetch: fetchImpl, force: true });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('never rejects, and keeps what it holds when a read fails', async () => {
    const reader = closingsReader(createDataFiles(['live/closings.json'], ROOT));
    const answers: (() => Promise<Response>)[] = [
      () => Promise.resolve(jsonResponse(AT_47)),
      () => Promise.reject(new TypeError('Failed to fetch')),
      () => Promise.resolve(jsonResponse({}, 500)),
    ];
    const fetchImpl = vi.fn(
      () => answers.shift()?.() ?? Promise.reject(new TypeError('Failed to fetch')),
    );
    await reader.read({ fetch: fetchImpl });
    expect(await reader.read({ fetch: fetchImpl, force: true })).toBe(reader.current);
    expect(await reader.read({ fetch: fetchImpl, force: true })).toBe(reader.current);
    expect(reader.current?.generated_at).toBe(AT_47.generated_at);
    // A build without the file: nothing to read.
    const none = closingsReader(createDataFiles([], ROOT));
    expect(await none.read({ fetch: fetchImpl })).toBeNull();
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('lights the map with a newer file a panel read, at once, with no read of its own', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    let current: unknown = AT_42;
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(current)));
    const lights: LitSchools[] = [];
    const shown: (string | null)[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: (lit) => lights.push(lit),
      onShown: (generatedAt) => shown.push(generatedAt),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0]);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    // A panel reads late in the minute and gets the newer file.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 0.95 - 10);
    current = AT_47;
    await closingsReader(files).read({ fetch: fetchImpl });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
    expect(shown.at(-1)).toBe(AT_47.generated_at);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // The map's own poll, just after the panel's read, takes what it read.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 0.05);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // The next is the map's next poll, a minute after its last: one read a minute in all.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    live.stop();
  });

  it('reads on after the device clock is set back, and darkens the map within one poll of a blank', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    let current: unknown = AT_47;
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(current)));
    const lights: LitSchools[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: (lit) => lights.push(lit),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
    // Network time puts a clock that ran an hour fast back; then a blank is published.
    vi.setSystemTime(NOON.getTime() - 60 * 60_000);
    current = BLANK;
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([]);
    // And a panel's read, after the clock went back, still reaches the network.
    current = at('2026-01-12T12:57:00Z', [[1, 0]]);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 0.9);
    expect((await closingsReader(files).read({ fetch: fetchImpl }))?.generated_at).toBe(
      '2026-01-12T12:57:00Z',
    );
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    live.stop();
  });

  it('times the reuse of a read by a clock that only moves forward, never the wall clock', async () => {
    let monotonic = 0;
    let wall = NOON.getTime();
    const reader = closingsReader(createDataFiles(['live/closings.json'], ROOT), {
      clocks: { wall: () => wall, monotonic: () => monotonic },
    });
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(AT_42)));
    await reader.read({ fetch: fetchImpl });
    // The wall clock goes back a day: the next poll still reads.
    wall -= 24 * 60 * 60_000;
    monotonic += LIVE_POLL_MS;
    await reader.read({ fetch: fetchImpl });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // Within the reuse window by both clocks: what is held.
    monotonic += 1000;
    wall += 1000;
    await reader.read({ fetch: fetchImpl });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // The device slept: its forward clock stood still, the wall clock did not. Read.
    wall += 8 * 60 * 60_000;
    await reader.read({ fetch: fetchImpl });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('gives up a read that never settles, so the next poll reads, and a blank still darkens', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const signals: (AbortSignal | undefined)[] = [];
    const answers: (() => Promise<Response>)[] = [
      () => Promise.resolve(jsonResponse(AT_47)),
      // A stalled connection: no answer, ever.
      () => new Promise<Response>(() => undefined),
      () => Promise.resolve(jsonResponse(BLANK)),
    ];
    const fetchImpl = vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init?.signal ?? undefined);
      return answers.shift()?.() ?? Promise.resolve(jsonResponse(BLANK));
    });
    const lights: LitSchools[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: (lit) => lights.push(lit),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
    // The second read hangs; a panel asking meanwhile shares it and is not held past the limit.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const panel = closingsReader(files).read({ fetch: fetchImpl });
    await vi.advanceTimersByTimeAsync(LIVE_READ_TIMEOUT_MS);
    expect(signals[1]?.aborted).toBe(true);
    expect((await panel)?.generated_at).toBe(AT_47.generated_at);
    // The next poll reads again, and takes the blank.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS - LIVE_READ_TIMEOUT_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([]);
    live.stop();
  });

  it('holds no later file back for a directory read that never settles', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const LATER = at('2026-01-12T12:49:00Z', [[1, 0]]);
    const answers = [AT_42, AT_47, BLANK];
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(answers.shift() ?? BLANK)));
    // From the second file on, the directory never comes (a stalled points read).
    let reads = 0;
    const directory = (): Promise<Directory | null> =>
      (reads += 1) === 1 ? Promise.resolve(DIRECTORY) : new Promise(() => undefined);
    const lights: LitSchools[] = [];
    const shown: (string | null)[] = [];
    const live = startLive({
      files,
      directory,
      onLight: (next) => lights.push(next),
      onShown: (generatedAt) => shown.push(generatedAt),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0]);
    // The next file's directory hangs: once the read's limit has passed, the map shows none of
    // the older file's lights, and no time.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(shown.at(-1)).toBe(AT_42.generated_at);
    await vi.advanceTimersByTimeAsync(LIVE_READ_TIMEOUT_MS);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([]);
    expect(shown.at(-1)).toBeNull();
    // The blank after it darkens the map at the next poll.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS - LIVE_READ_TIMEOUT_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(shown.at(-1)).toBe(BLANK.generated_at);
    live.stop();
    // A late directory is asked for again at the next poll, and the file then lights.
    const again = createDataFiles(['live/closings.json'], ROOT);
    let hang = true;
    const lightsAgain: LitSchools[] = [];
    const second = startLive({
      files: again,
      directory: () =>
        hang ? new Promise<Directory | null>(() => undefined) : Promise.resolve(DIRECTORY),
      onLight: (next) => lightsAgain.push(next),
      fetch: vi.fn(() => Promise.resolve(jsonResponse(LATER))),
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(LIVE_READ_TIMEOUT_MS + 10);
    expect(lightsAgain).toEqual([]);
    hang = false;
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect([...(lightsAgain.at(-1)?.schools ?? [])]).toEqual([1]);
    second.stop();
  });

  it('gives up, on waking, a read that was on its way when the device went to sleep', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const signals: (AbortSignal | undefined)[] = [];
    const answers: (() => Promise<Response>)[] = [
      () => Promise.resolve(jsonResponse(AT_47)),
      // Asked as the lid shut: its connection does not survive the sleep.
      () => new Promise<Response>(() => undefined),
      () => Promise.resolve(jsonResponse(BLANK)),
    ];
    const fetchImpl = vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init?.signal ?? undefined);
      return answers.shift()?.() ?? Promise.resolve(jsonResponse(BLANK));
    });
    const lights: LitSchools[] = [];
    // The reader's forward clock stands still throughout (as it may while a device sleeps), so
    // only the wall clock can tell the read on its way is past its limit.
    const reader = closingsReader(files, {
      clocks: { wall: () => Date.now(), monotonic: () => 0 },
    });
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: (next) => lights.push(next),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // Asleep for an hour: neither the read's timer nor the forward clock moved; the wall did.
    vi.setSystemTime(Date.now() + 60 * 60_000);
    await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
    expect(signals[1]?.aborted).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(reader.current?.generated_at).toBe(BLANK.generated_at);
    expect([...(lights.at(-1)?.schools ?? [])]).toEqual([]);
    live.stop();
  });

  it('gives up a read that hangs once its limit passes, with no one asking again', async () => {
    const reader = closingsReader(createDataFiles(['live/closings.json'], ROOT));
    const signals: (AbortSignal | undefined)[] = [];
    const answers: (() => Promise<Response>)[] = [
      () => Promise.resolve(jsonResponse(AT_47)),
      () => new Promise<Response>(() => undefined),
    ];
    const fetchImpl = vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init?.signal ?? undefined);
      return answers.shift()?.() ?? Promise.resolve(jsonResponse(BLANK));
    });
    await reader.read({ fetch: fetchImpl });
    let settled: ClosingsFile | null | undefined;
    void reader.read({ fetch: fetchImpl, force: true }).then((file) => {
      settled = file;
    });
    await vi.advanceTimersByTimeAsync(LIVE_READ_TIMEOUT_MS - 1);
    expect(settled).toBeUndefined();
    expect(signals[1]?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(settled?.generated_at).toBe(AT_47.generated_at);
    expect(signals[1]?.aborted).toBe(true);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('reads again for a forced read asked while another is on its way', async () => {
    const reader = closingsReader(createDataFiles(['live/closings.json'], ROOT));
    let answer!: (response: Response) => void;
    const answers: (() => Promise<Response>)[] = [
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
      () => Promise.resolve(jsonResponse(AT_47)),
    ];
    const fetchImpl = vi.fn(() => answers.shift()?.() ?? Promise.resolve(jsonResponse(BLANK)));
    const first = reader.read({ fetch: fetchImpl });
    // The worker says it holds a newer copy while the first read is on its way.
    const forced = reader.read({ fetch: fetchImpl, force: true });
    // An unforced ask meanwhile shares the read on its way.
    const shared = reader.read({ fetch: fetchImpl });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    answer(jsonResponse(AT_42));
    expect((await first)?.generated_at).toBe(AT_42.generated_at);
    expect((await shared)?.generated_at).toBe(AT_42.generated_at);
    expect((await forced)?.generated_at).toBe(AT_47.generated_at);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  for (const after of [LIVE_READ_TIMEOUT_MS + 1000, 2 * LIVE_READ_TIMEOUT_MS + 5000]) {
    it(`lights a file as soon as a directory late by ${String(after / 1000)} s comes, before the next poll`, async () => {
      const files = createDataFiles(['live/closings.json'], ROOT);
      const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(AT_47)));
      let come!: (directory: Directory | null) => void;
      const slow = new Promise<Directory | null>((resolve) => {
        come = resolve;
      });
      const lights: LitSchools[] = [];
      const shown: (string | null)[] = [];
      const live = startLive({
        files,
        // One directory read, shared, as app/data.ts shares it: slow to come.
        directory: () => slow,
        onLight: (next) => lights.push(next),
        onShown: (generatedAt) => shown.push(generatedAt),
        fetch: fetchImpl,
        now: () => NOON,
        clock: () => 1000,
        host: fakeHost(),
      });
      await vi.advanceTimersByTimeAsync(LIVE_READ_TIMEOUT_MS + 10);
      expect(lights).toEqual([]);
      expect(shown.at(-1) ?? null).toBeNull();
      await vi.advanceTimersByTimeAsync(after - LIVE_READ_TIMEOUT_MS - 10);
      come(DIRECTORY);
      await vi.advanceTimersByTimeAsync(10);
      expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
      expect(shown.at(-1)).toBe(AT_47.generated_at);
      // Lit from what the reader held: no read of its own.
      expect(fetchImpl).toHaveBeenCalledTimes(1);
      live.stop();
    });
  }

  it('stops hearing the reader when stopped, so a later file reaches no stopped map', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const reader = closingsReader(files);
    const stops: ReturnType<typeof vi.fn>[] = [];
    const subscribe = reader.subscribe.bind(reader);
    const spy = vi.spyOn(reader, 'subscribe').mockImplementation((listener) => {
      const stop = vi.fn(subscribe(listener));
      stops.push(stop);
      return stop;
    });
    let answer: unknown = AT_42;
    const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(answer)));
    const directory = vi.fn(() => Promise.resolve<Directory | null>(DIRECTORY));
    const lights: LitSchools[] = [];
    const live = startLive({
      files,
      directory,
      onLight: (next) => lights.push(next),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(stops).toHaveLength(1);
    live.stop();
    expect(stops[0]).toHaveBeenCalledTimes(1);
    const before = { lights: lights.length, directory: directory.mock.calls.length };
    answer = AT_47;
    await reader.read({ fetch: fetchImpl, force: true });
    await vi.advanceTimersByTimeAsync(10);
    expect(reader.current?.generated_at).toBe(AT_47.generated_at);
    expect(lights.length).toBe(before.lights);
    expect(directory.mock.calls.length).toBe(before.directory);
    spy.mockRestore();
  });

  it('makes one read a minute for the map and a panel at any offset between their polls', async () => {
    for (const offset of [0, 10_000, 29_990, 30_000, 30_010, 45_000, 54_000, 59_990]) {
      const reader = closingsReader(createDataFiles(['live/closings.json'], ROOT));
      const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(AT_42)));
      const poll = (): void => void reader.read({ fetch: fetchImpl });
      const host = fakeHost();
      // The map reads as it starts and polls each minute; the panel opens `offset` later.
      poll();
      const stopMap = pollWhileVisible(poll, LIVE_POLL_MS, { host });
      await vi.advanceTimersByTimeAsync(offset);
      poll();
      const stopPanel = pollWhileVisible(poll, LIVE_POLL_MS, { host });
      const before = fetchImpl.mock.calls.length;
      await vi.advanceTimersByTimeAsync(10 * LIVE_POLL_MS);
      expect(fetchImpl.mock.calls.length - before, `offset ${String(offset)}`).toBe(10);
      stopMap();
      stopPanel();
    }
  });
});

describe('the next read after a show, a wake or a reconnect', () => {
  const at = (generatedAt: string, rows: Parameters<typeof testDay>[1] = []) =>
    testClosings(generatedAt, META, rows.length === 0 ? [] : [testDay('2026-01-12', rows)]);
  const LIT = at('2026-01-12T17:59:00Z', [
    [0, 0],
    [1, 1],
  ]);
  const BLANK = at('2026-01-12T18:01:00Z');

  /** The map, a host with a window to send events to, and the moments its reads went out. */
  function page() {
    const win = new EventTarget();
    const host = {
      ...fakeHost(),
      addEventListener: win.addEventListener.bind(win),
      removeEventListener: win.removeEventListener.bind(win),
    };
    const files = createDataFiles(['live/closings.json'], ROOT);
    const reads: number[] = [];
    let current: unknown = LIT;
    const fetchImpl = vi.fn(() => {
      // performance.now(): the forward clock, which a sleep's jump of the wall clock leaves.
      reads.push(performance.now());
      return Promise.resolve(jsonResponse(current));
    });
    const lights: LitSchools[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: (next) => lights.push(next),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host,
    });
    const reader = closingsReader(files);
    /** A panel beside the map: it polls through the same reader, paced by it. */
    const panel = (): (() => void) =>
      pollWhileVisible(() => void reader.read({ fetch: fetchImpl }), LIVE_POLL_MS, {
        host,
        pace: reader,
      });
    const visibility = (state: DocumentVisibilityState): void => {
      host.document.visibilityState = state;
      host.document.dispatchEvent(new Event('visibilitychange'));
    };
    return {
      live,
      host,
      win,
      reads,
      reader,
      fetchImpl,
      panel,
      visibility,
      dark: () => (lights.at(-1)?.schools.size ?? -1) === 0,
      publish: (file: unknown) => {
        current = file;
      },
    };
  }

  /** The longest wait between two reads that went out, from `from` on. */
  const longestGap = (reads: readonly number[], from: number): number => {
    const after = reads.filter((time) => time >= from);
    return Math.max(...after.slice(1).map((time, i) => time - (after[i] ?? time)));
  };

  for (const withPanel of [false, true]) {
    const beside = withPanel ? ', with a panel open beside the map' : '';
    it(`reads within a poll of the read made when the page is shown again${beside}`, async () => {
      const p = page();
      await vi.advanceTimersByTimeAsync(10);
      const stopPanel = withPanel ? p.panel() : () => undefined;
      await vi.advanceTimersByTimeAsync(1000);
      p.visibility('hidden');
      // A phone locked at 1 s and unlocked at 67 s.
      await vi.advanceTimersByTimeAsync(66_000);
      p.visibility('visible');
      await vi.advanceTimersByTimeAsync(10);
      const shownRead = p.reads.at(-1) ?? 0;
      expect(performance.now() - shownRead).toBeLessThan(100);
      // A blank published just after that read darkens the map within a poll of it.
      p.publish(BLANK);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect(p.dark()).toBe(true);
      await vi.advanceTimersByTimeAsync(5 * LIVE_POLL_MS);
      expect(longestGap(p.reads, shownRead)).toBeLessThanOrEqual(LIVE_POLL_MS);
      // And still one read a poll, not more.
      expect(p.reads.filter((time) => time > shownRead).length).toBe(6);
      stopPanel();
      p.live.stop();
    });

    it(`reads within a poll of the read made on waking from a sleep${beside}`, async () => {
      const p = page();
      await vi.advanceTimersByTimeAsync(10);
      const stopPanel = withPanel ? p.panel() : () => undefined;
      await vi.advanceTimersByTimeAsync(30_000);
      // Asleep two hours: the wall clock jumps, the timers and the forward clock do not.
      vi.setSystemTime(Date.now() + 2 * 60 * 60_000);
      await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
      const wakeRead = p.reads.at(-1) ?? 0;
      expect(performance.now() - wakeRead).toBeLessThan(WAKE_CHECK_MS);
      expect(p.reads.length).toBe(2);
      p.publish(BLANK);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect(p.dark()).toBe(true);
      await vi.advanceTimersByTimeAsync(5 * LIVE_POLL_MS);
      expect(longestGap(p.reads, wakeRead)).toBeLessThanOrEqual(LIVE_POLL_MS);
      stopPanel();
      p.live.stop();
    });
  }

  it('reads within a poll of a read another made, though that one then stops', async () => {
    const p = page();
    await vi.advanceTimersByTimeAsync(10);
    const stopPanel = p.panel();
    await vi.advanceTimersByTimeAsync(40_000);
    // The worker said it holds a newer copy: a forced read, 40 s into the map's minute.
    await p.reader.read({ fetch: p.fetchImpl, force: true });
    const forced = p.reads.at(-1) ?? 0;
    stopPanel();
    p.publish(BLANK);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(p.dark()).toBe(true);
    await vi.advanceTimersByTimeAsync(5 * LIVE_POLL_MS);
    expect(longestGap(p.reads, forced)).toBeLessThanOrEqual(LIVE_POLL_MS);
    p.live.stop();
  });

  it('reads at once when the device comes back online, once for the map and a panel', async () => {
    const p = page();
    await vi.advanceTimersByTimeAsync(10);
    const stopPanel = p.panel();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS + 10);
    const before = p.reads.length;
    // Offline 10 s after the last read; a blank is published meanwhile; back online.
    await vi.advanceTimersByTimeAsync(10_000);
    p.publish(BLANK);
    p.win.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(10);
    expect(p.reads.length).toBe(before + 1);
    expect(p.dark()).toBe(true);
    // And the next read comes a poll after that one.
    const online = p.reads.at(-1) ?? 0;
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(p.reads.length).toBe(before + 2);
    expect((p.reads.at(-1) ?? 0) - online).toBeLessThanOrEqual(LIVE_POLL_MS);
    // A hidden page reads nothing for it.
    p.visibility('hidden');
    p.win.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(10);
    expect(p.reads.length).toBe(before + 2);
    stopPanel();
    p.live.stop();
  });
});

describe('the map beside a panel, with the ingest stopped', () => {
  // The last file came Monday afternoon; the ingest then stopped, so it is served all night.
  const MONDAY = testClosings('2026-01-12T17:40:00Z', META, [testDay('2026-01-12', [[0, 0]])]);
  /** 04:00 UTC Tuesday: midnight in the East, and Monday is no longer today everywhere. */
  const TURN = Date.parse('2026-01-13T04:00:00Z');

  for (const panelFirst of [false, true]) {
    const order = panelFirst ? 'opened before the map (a ?school= or ?zip= link)' : 'opened after';
    it(`goes dark within a poll of the day turning, with a panel ${order}, and both run every poll on one read`, async () => {
      const files = createDataFiles(['live/closings.json'], ROOT);
      const reader = closingsReader(files);
      const host = fakeHost();
      const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(MONDAY)));
      /** When the panel's own work ran: it works its view out again against the time. */
      const panelRuns: number[] = [];
      const panel = (): (() => void) =>
        pollWhileVisible(
          () => {
            panelRuns.push(Date.now());
            void reader.read({ fetch: fetchImpl });
          },
          LIVE_POLL_MS,
          { host, pace: reader },
        );
      let stopPanel = panelFirst ? panel() : null;
      const lights: { at: number; size: number }[] = [];
      const live = startLive({
        files,
        directory: () => Promise.resolve<Directory | null>(DIRECTORY),
        onLight: (lit) => lights.push({ at: Date.now(), size: lit.schools.size }),
        fetch: fetchImpl,
        now: () => new Date(Date.now()),
        clock: () => 1000,
        host,
      });
      await vi.advanceTimersByTimeAsync(10);
      stopPanel ??= panel();
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect(lights.at(-1)?.size).toBe(1);
      const reads = fetchImpl.mock.calls.length;
      const runs = panelRuns.length;
      // On to 04:00 UTC and a poll past it, the same file all the while.
      const polls = Math.ceil((TURN - Date.now()) / LIVE_POLL_MS) + 1;
      await vi.advanceTimersByTimeAsync(polls * LIVE_POLL_MS);
      const dark = lights.find((light) => light.at >= TURN && light.size === 0);
      expect(dark, 'dark after the day turned').toBeDefined();
      expect((dark?.at ?? Infinity) - TURN).toBeLessThanOrEqual(LIVE_POLL_MS);
      expect(lights.at(-1)?.size).toBe(0);
      // One read a poll for the two, and the panel's own work every poll.
      expect(fetchImpl.mock.calls.length - reads).toBe(polls);
      expect(panelRuns.length - runs).toBeGreaterThanOrEqual(polls);
      const gaps = panelRuns.slice(runs + 1).map((time, i) => time - (panelRuns[runs + i] ?? 0));
      expect(Math.max(...gaps)).toBeLessThanOrEqual(LIVE_POLL_MS);
      stopPanel();
      live.stop();
    });
  }
});

describe('a read hung on a lost connection', () => {
  it('is given up when the device comes back online, and a read made at once, one for the map and a panel', async () => {
    const win = new EventTarget();
    const host = {
      ...fakeHost(),
      addEventListener: win.addEventListener.bind(win),
      removeEventListener: win.removeEventListener.bind(win),
    };
    const files = createDataFiles(['live/closings.json'], ROOT);
    const reader = closingsReader(files);
    const LIT = testClosings('2026-01-12T17:59:00Z', META, [testDay('2026-01-12', [[0, 0]])]);
    const BLANK = testClosings('2026-01-12T18:01:00Z', META, []);
    let hang = false;
    let current: unknown = LIT;
    const signals: AbortSignal[] = [];
    const fetchImpl = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal);
      return hang ? new Promise<Response>(() => undefined) : Promise.resolve(jsonResponse(current));
    });
    const lights: LitSchools[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve<Directory | null>(DIRECTORY),
      onLight: (lit) => lights.push(lit),
      fetch: fetchImpl,
      now: () => NOON,
      clock: () => 1000,
      host,
    });
    const stopPanel = pollWhileVisible(() => void reader.read({ fetch: fetchImpl }), LIVE_POLL_MS, {
      host,
      pace: reader,
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(lights.at(-1)?.schools.size).toBe(1);
    // The connection drops (lie-fi): the next poll's read hangs.
    hang = true;
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    const before = fetchImpl.mock.calls.length;
    expect(signals.at(-1)?.aborted).toBe(false);
    // 5 s later the device is back online, and a blank has been published.
    await vi.advanceTimersByTimeAsync(5_000);
    hang = false;
    current = BLANK;
    win.dispatchEvent(new Event('online'));
    await vi.advanceTimersByTimeAsync(10);
    // The hung read is given up and one read made at once, for the map and the panel both.
    expect(signals[before - 1]?.aborted).toBe(true);
    expect(fetchImpl.mock.calls.length).toBe(before + 1);
    expect(lights.at(-1)?.schools.size).toBe(0);
    stopPanel();
    live.stop();
  });
});

describe('a device clock that is wrong', () => {
  const stamp = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
  const lit = (ms: number) =>
    testClosings(stamp(ms), META, [
      testDay('2026-01-12', [
        [0, 0],
        [1, 1],
      ]),
    ]);
  const blank = (ms: number) => testClosings(stamp(ms), META, []);

  it('never decides which file is newer: only the files’ own stamps do', () => {
    const held = blank(NOON.getTime());
    const far = blank(Date.parse('2099-01-01T00:00:00Z'));
    expect(newerClosings(held, far)).toBe(far);
    expect(newerClosings(far, held)).toBe(far);
    expect(newerClosings(null, far)).toBe(far);
    expect(newerClosings(held, blank(NOON.getTime() - 60_000))).toBe(held);
  });

  for (const back of [15, 60]) {
    it(`darkens the map and the line moves on, within one poll of a blank, after the clock went back ${String(back)} minutes`, async () => {
      const files = createDataFiles(['live/closings.json'], ROOT);
      const real = NOON.getTime();
      // Taken at the device's own now; then the device's clock goes back, and a blank is
      // published: every file from here on is stamped well past the device's clock.
      let current: unknown = lit(real);
      const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(current)));
      const lights: LitSchools[] = [];
      const shown: (string | null)[] = [];
      const live = startLive({
        files,
        directory: () => Promise.resolve(DIRECTORY),
        onLight: (next) => lights.push(next),
        onShown: (generatedAt) => shown.push(generatedAt),
        fetch: fetchImpl,
        now: () => new Date(Date.now()),
        clock: () => 1000,
        host: fakeHost(),
      });
      await vi.advanceTimersByTimeAsync(10);
      expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
      vi.setSystemTime(real - back * 60_000);
      current = blank(real + 60_000);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect(fetchImpl).toHaveBeenCalledTimes(2);
      expect([...(lights.at(-1)?.schools ?? [])]).toEqual([]);
      expect(shown.at(-1)).toBe(stamp(real + 60_000));
      // New closings after it light within one poll too.
      current = lit(real + 2 * 60_000);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect([...(lights.at(-1)?.schools ?? [])]).toEqual([0, 1]);
      expect(closingsReader(files).current?.generated_at).toBe(stamp(real + 2 * 60_000));
      live.stop();
    });
  }

  it('never calls a file live while newer ones go untaken, on a clock an hour slow', async () => {
    const files = createDataFiles(['live/closings.json'], ROOT);
    const slow = 60 * 60_000;
    // The device's clock runs an hour behind the ingest's; a file is published every minute.
    const realNow = (): number => Date.now() + slow;
    const fetchImpl = vi.fn(() =>
      Promise.resolve(jsonResponse(blank(Math.floor(realNow() / 60_000) * 60_000))),
    );
    const shown: (string | null)[] = [];
    const live = startLive({
      files,
      directory: () => Promise.resolve(DIRECTORY),
      onLight: () => undefined,
      onShown: (generatedAt) => shown.push(generatedAt),
      fetch: fetchImpl,
      now: () => new Date(Date.now()),
      clock: () => 1000,
      host: fakeHost(),
    });
    await vi.advanceTimersByTimeAsync(10);
    for (let poll = 0; poll < 90; poll += 1) {
      const published = stamp(Math.floor(realNow() / 60_000) * 60_000);
      // Each minute's file is taken, and its line, read on the slow clock, is never Live.
      expect(shown.at(-1), `poll ${String(poll)}`).toBe(published);
      const line = updateState({
        generatedAt: published,
        online: true,
        timeZone: 'America/Chicago',
        now: new Date(Date.now()),
      });
      expect(line?.live, `poll ${String(poll)}`).toBe(false);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    }
    expect(fetchImpl).toHaveBeenCalledTimes(91);
    live.stop();
  });
});

describe('a device that slept with the page open', () => {
  it('reads at once on waking, though its timers and forward clock were held back', async () => {
    const host = fakeHost();
    const read = vi.fn();
    let monotonic = 0;
    const stop = pollWhileVisible(read, LIVE_POLL_MS, {
      host,
      clocks: { wall: () => Date.now(), monotonic: () => monotonic },
    });
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    monotonic += LIVE_POLL_MS;
    expect(read).toHaveBeenCalledTimes(1);
    // Asleep overnight: the wall clock jumps, nothing else moves.
    vi.setSystemTime(Date.now() + 9 * 60 * 60_000);
    await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
    expect(read).toHaveBeenCalledTimes(2);
    stop();
  });

  it('reads when the page is shown again from the back-forward cache, if a poll is due', () => {
    const host = new EventTarget();
    const read = vi.fn();
    const stop = pollWhileVisible(read, LIVE_POLL_MS, {
      host: {
        ...fakeHost(),
        addEventListener: host.addEventListener.bind(host),
        removeEventListener: host.removeEventListener.bind(host),
      },
    });
    host.dispatchEvent(new Event('pageshow'));
    expect(read).not.toHaveBeenCalled();
    vi.setSystemTime(Date.now() + 2 * LIVE_POLL_MS);
    host.dispatchEvent(new Event('pageshow'));
    expect(read).toHaveBeenCalledTimes(1);
    stop();
    vi.setSystemTime(Date.now() + 2 * LIVE_POLL_MS);
    host.dispatchEvent(new Event('pageshow'));
    expect(read).toHaveBeenCalledTimes(1);
  });

  it('reads nothing while hidden, whatever wakes it: a gap in the clock, focus, pageshow or resume', async () => {
    const win = new EventTarget();
    const host = {
      ...fakeHost(),
      addEventListener: win.addEventListener.bind(win),
      removeEventListener: win.removeEventListener.bind(win),
    };
    const read = vi.fn();
    const stop = pollWhileVisible(read, LIVE_POLL_MS, { host });
    await vi.advanceTimersByTimeAsync(2 * LIVE_POLL_MS);
    const seen = read.mock.calls.length;
    // A poll is due as the page is hidden.
    vi.setSystemTime(Date.now() + 2 * LIVE_POLL_MS);
    host.document.visibilityState = 'hidden';
    host.document.dispatchEvent(new Event('visibilitychange'));
    for (let i = 0; i < 30; i += 1) {
      // A hidden page's timers run at most once a minute: each wake check sees a minute's gap.
      vi.setSystemTime(Date.now() + LIVE_POLL_MS);
      await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
      win.dispatchEvent(new Event('focus'));
      win.dispatchEvent(new Event('pageshow'));
      host.document.dispatchEvent(new Event('resume'));
      host.document.dispatchEvent(new Event('visibilitychange'));
    }
    expect(read.mock.calls.length - seen).toBe(0);
    // Shown again: it reads at once.
    host.document.visibilityState = 'visible';
    host.document.dispatchEvent(new Event('visibilitychange'));
    expect(read.mock.calls.length - seen).toBe(1);
    stop();
  });
});

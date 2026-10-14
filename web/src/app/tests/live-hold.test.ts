/**
 * The live glow held while a replay is on (app/data.ts LiveGlow.hold): a
 * live paint never lands over a replay, and letting go shows live as it is
 * now, once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NOTHING_LIT } from '../../data/closings';
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
} from '../../data/tests/builders';
import type { Glow } from '../../map/glow-mount';
import { SHOW_ALL } from '../../state/filter';
import { notLive, startLiveGlow } from '../data';
import type { AppData } from '../data';

const ROOT = 'https://snow.test/data/';
const SCHOOLS = [
  { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: -1 },
  { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: -1 },
];
const META = testMeta(SCHOOLS);
const POINTS = parsePoints(testPoints(SCHOOLS, 0), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
/** A SYNTHETIC live file: one school closed. */
const FIRST = testClosings('2026-01-12T12:42:00Z', META, [testDay('2026-01-12', [[0, 0]])]);

function withLive(): AppData {
  const source: DirectorySource = { get: () => Promise.resolve(DIRECTORY) };
  return {
    files: createDataFiles(['live/closings.json', 'schools/meta.json', 'schools/points.bin'], ROOT),
    directories: () => Promise.resolve(source),
  };
}

/** A glow layer whose arrival the test decides, and what it was told to light. */
function deferredGlow() {
  const lit: LitSchools[] = [];
  const layer = { light: (next: LitSchools) => lit.push(next) } as unknown as Glow;
  let arrive: () => void = () => undefined;
  const glow = new Promise<Glow | null>((resolve) => {
    arrive = () => {
      resolve(layer);
    };
  });
  return { glow, lit, arrive };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-01-12T18:00:00Z'));
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(jsonResponse(FIRST))),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the live glow, held', () => {
  it('drops a live paint queued before the hold: nothing lands over a replay', async () => {
    const { glow, lit, arrive } = deferredGlow();
    const live = await startLiveGlow(withLive(), glow);
    await settle();
    // The first file is read and its paint waits for the layer; then a replay comes on.
    live.hold(true);
    arrive();
    await settle();
    expect(lit).toEqual([]);
    live.stop();
  });

  it('shows nothing while held, and on letting go paints the latest once, without a pulse', async () => {
    const { glow, lit, arrive } = deferredGlow();
    arrive();
    const shown: (string | null)[] = [];
    const counts: (StatusCounts | null)[] = [];
    const live = await startLiveGlow(withLive(), glow, {
      onShown: (at) => shown.push(at),
      onCounts: (next) => counts.push(next),
    });
    await settle();
    expect(lit).toHaveLength(1);
    expect(shown).toEqual(['2026-01-12T12:42:00Z']);
    expect(counts).toEqual([[1, 0, 0, 0]]);

    live.hold(true);
    // A filter change while held: kept, not shown.
    live.filter({ ...SHOW_ALL, private: false });
    await settle();
    expect(lit).toHaveLength(1);
    expect(shown).toHaveLength(1);
    expect(counts).toHaveLength(1);

    live.hold(false);
    await settle();
    // The file as it was, painted again once without a pulse, and its time and counts given again.
    expect(lit).toHaveLength(2);
    expect(lit[1]?.bornAt).toBeUndefined();
    expect(shown).toEqual(['2026-01-12T12:42:00Z', '2026-01-12T12:42:00Z']);
    expect(counts).toEqual([
      [1, 0, 0, 0],
      [1, 0, 0, 0],
    ]);
    live.stop();
  });

  it('lands two queued paints in order: an older one never lands after a newer', async () => {
    const { glow, lit, arrive } = deferredGlow();
    const live = await startLiveGlow(withLive(), glow);
    await settle();
    live.filter({ ...SHOW_ALL, private: false });
    live.filter(SHOW_ALL);
    arrive();
    await settle();
    // Only the newest of the paints queued lands.
    expect(lit).toHaveLength(1);
    expect([...(lit[0]?.schools ?? [])]).toEqual([0]);
    live.stop();
  });

  it('with no live file, letting go clears the replay: nothing lit, no time, no counts', async () => {
    const { glow, lit, arrive } = deferredGlow();
    arrive();
    const shown: (string | null)[] = [];
    const counts: (StatusCounts | null)[] = [];
    const none = notLive(glow, {
      onShown: (at) => shown.push(at),
      onCounts: (next) => counts.push(next),
    });
    none.hold(true);
    none.hold(false);
    await settle();
    expect(lit).toEqual([NOTHING_LIT]);
    expect(shown).toEqual([null]);
    expect(counts).toEqual([null]);
    // Letting go of what was never held changes nothing.
    none.hold(false);
    await settle();
    expect(lit).toHaveLength(1);
  });

  it('starts held for a link to a past day: live never paints first', async () => {
    const { glow, lit, arrive } = deferredGlow();
    arrive();
    const shown: (string | null)[] = [];
    const live = await startLiveGlow(
      withLive(),
      glow,
      { onShown: (at) => shown.push(at) },
      SHOW_ALL,
      {
        held: true,
      },
    );
    await settle();
    expect(lit).toEqual([]);
    expect(shown).toEqual([]);
    live.hold(false);
    await settle();
    expect(lit).toHaveLength(1);
    expect(shown).toEqual(['2026-01-12T12:42:00Z']);
    live.stop();
  });
});

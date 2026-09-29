/**
 * Failed tiles, asked for again until they come: MapLibre itself asks for a
 * tile once, and a failed one stays failed for as long as it is in view.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HEAL_BACKOFF, HealRounds, failedTiles, healTiles } from '../heal';

/** A tile manager's tiles, by id: their states. */
type Tiles = Map<string, { state: string }>;

/** Just enough of a map for the healer: its events, its sources' tiles, and its next frame. */
function fakeMap(sources: Record<string, Tiles>) {
  const listeners = new Map<string, Set<(event: unknown) => void>>();
  const removed: string[] = [];
  let updates = 0;
  const map = {
    style: {
      tileManagers: Object.fromEntries(
        Object.entries(sources).map(([id, tiles]) => [
          id,
          {
            getIds: () => [...tiles.keys()],
            getTileByID: (tile: string) => tiles.get(tile),
            _removeTile: (tile: string) => {
              removed.push(`${id}/${tile}`);
              tiles.delete(tile);
            },
          },
        ]),
      ),
    },
    on(type: string, listener: (event: unknown) => void) {
      let set = listeners.get(type);
      if (set === undefined) {
        set = new Set();
        listeners.set(type, set);
      }
      set.add(listener);
      return map;
    },
    off(type: string, listener: (event: unknown) => void) {
      listeners.get(type)?.delete(listener);
      return map;
    },
    _update() {
      updates++;
      return map;
    },
  };
  const fire = (type: string, event: unknown = {}): void => {
    for (const listener of listeners.get(type) ?? []) listener(event);
  };
  return {
    map: map as unknown as MapLibreMap,
    fire,
    removed,
    updates: () => updates,
    listening: () => [...listeners.values()].reduce((sum, set) => sum + set.size, 0),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, 'random').mockReturnValue(0.5);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('rounds of asking again', () => {
  it('wait longer each time, up to the last wait, and start over once a tile comes', () => {
    const rounds = new HealRounds();
    const waits = HEAL_BACKOFF.map(() => rounds.next(() => 0.5));
    expect(waits).toEqual([...HEAL_BACKOFF]);
    expect(rounds.next(() => 0.5)).toBe(HEAL_BACKOFF[HEAL_BACKOFF.length - 1]);
    rounds.reset();
    expect(rounds.next(() => 0.5)).toBe(HEAL_BACKOFF[0]);
  });

  it('grow to a minute apart while the host keeps failing, no longer', () => {
    expect(HEAL_BACKOFF.at(-1)).toBe(60_000);
    expect([...HEAL_BACKOFF].sort((a, b) => a - b)).toEqual([...HEAL_BACKOFF]);
  });
});

describe('failed tiles', () => {
  it('are asked for again after a wait, as new tiles, until they come', () => {
    const streets: Tiles = new Map([
      ['a', { state: 'errored' }],
      ['b', { state: 'loaded' }],
      ['c', { state: 'errored' }],
    ]);
    const { map, fire, removed, updates } = fakeMap({ streets });
    healTiles(map, ['streets']);
    expect(failedTiles(map, 'streets')).toEqual(['a', 'c']);
    fire('error', { sourceId: 'streets' });
    vi.advanceTimersByTime((HEAL_BACKOFF[0] ?? 0) - 1);
    expect(removed).toEqual([]);
    vi.advanceTimersByTime(1);
    // Dropped: the map's next frame asks for them afresh.
    expect(removed).toEqual(['streets/a', 'streets/c']);
    expect(updates()).toBe(1);

    // They failed again: the next round waits longer.
    streets.set('a', { state: 'errored' });
    fire('error', { sourceId: 'streets' });
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(removed).toHaveLength(2);
    vi.advanceTimersByTime((HEAL_BACKOFF[1] ?? 0) - (HEAL_BACKOFF[0] ?? 0));
    expect(removed).toEqual(['streets/a', 'streets/c', 'streets/a']);

    // One came: the next failure is asked for again soonest.
    fire('sourcedata', { sourceId: 'streets', tile: { state: 'loaded' } });
    streets.set('d', { state: 'errored' });
    fire('error', { sourceId: 'streets' });
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(removed.at(-1)).toBe('streets/d');
  });

  it('while they keep failing, are asked for one a round, and all once that one comes', () => {
    const streets: Tiles = new Map([
      ['a', { state: 'errored' }],
      ['b', { state: 'errored' }],
      ['c', { state: 'errored' }],
    ]);
    const { map, fire, removed } = fakeMap({ streets });
    healTiles(map, ['streets']);
    const failAgain = (...ids: string[]): void => {
      for (const id of ids) streets.set(id, { state: 'errored' });
      fire('error', { sourceId: 'streets' });
    };
    fire('error', { sourceId: 'streets' });
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(removed).toEqual(['streets/a', 'streets/b', 'streets/c']);
    // All failed again: from now on each round asks for one of them.
    failAgain('a', 'b', 'c');
    vi.advanceTimersByTime(HEAL_BACKOFF[1] ?? 0);
    expect(removed.slice(3)).toEqual(['streets/a']);
    failAgain('a');
    vi.advanceTimersByTime(HEAL_BACKOFF[2] ?? 0);
    expect(removed.slice(4)).toEqual(['streets/b']);
    // That one came: the next round asks for the rest, soonest.
    fire('sourcedata', { sourceId: 'streets', tile: { state: 'loaded' } });
    fire('idle');
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(removed.slice(5).sort()).toEqual(['streets/a', 'streets/c']);
  });

  it('are asked for once a round, however many fail in it', () => {
    const streets: Tiles = new Map([['a', { state: 'errored' }]]);
    const { map, fire, updates } = fakeMap({ streets });
    healTiles(map, ['streets']);
    for (let i = 0; i < 10; i++) fire('error', { sourceId: 'streets' });
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(updates()).toBe(1);
  });

  it('left failed at rest are asked for again too', () => {
    const streets: Tiles = new Map([['a', { state: 'errored' }]]);
    const { map, fire, removed } = fakeMap({ streets });
    healTiles(map, ['streets']);
    fire('idle');
    vi.advanceTimersByTime(HEAL_BACKOFF[0] ?? 0);
    expect(removed).toEqual(['streets/a']);
  });

  it('are asked for at once when the network comes back', () => {
    const streets: Tiles = new Map([['a', { state: 'errored' }]]);
    const { map, fire, removed } = fakeMap({ streets });
    healTiles(map, ['streets']);
    fire('error', { sourceId: 'streets' });
    window.dispatchEvent(new Event('online'));
    vi.advanceTimersByTime(0);
    expect(removed).toEqual(['streets/a']);
  });

  it('of other sources are left to the map', () => {
    const other: Tiles = new Map([['a', { state: 'errored' }]]);
    const { map, fire, removed } = fakeMap({ other });
    healTiles(map, ['streets']);
    fire('error', { sourceId: 'other' });
    fire('idle');
    vi.advanceTimersByTime(60_000);
    expect(removed).toEqual([]);
  });

  it('are left alone once the map is gone', () => {
    const streets: Tiles = new Map([['a', { state: 'errored' }]]);
    const { map, fire, removed, listening } = fakeMap({ streets });
    const stop = healTiles(map, ['streets']);
    fire('error', { sourceId: 'streets' });
    stop();
    vi.advanceTimersByTime(60_000);
    window.dispatchEvent(new Event('online'));
    vi.advanceTimersByTime(0);
    expect(removed).toEqual([]);
    expect(listening()).toBe(0);
  });
});

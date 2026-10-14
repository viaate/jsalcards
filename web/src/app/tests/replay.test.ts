/**
 * Replay mode's controller (app/replay.ts): two-phase entry, tickets, history,
 * and a link's day that cannot be shown.
 */
import { describe, expect, it, vi } from 'vitest';

import { NOTHING_LIT } from '../../data/closings';
import type { LitSchools, StatusCounts } from '../../data/closings';
import { createDataFiles } from '../../data/files';
import { createDirectory, parsePoints } from '../../data/directory';
import type { DirectorySource } from '../../data/directory';
import { jsonResponse, testMeta, testPoints, testReplay } from '../../data/tests/builders';
import type { Glow } from '../../map/glow-mount';
import { SHOW_ALL } from '../../state/filter';
import type { LocalDate } from '../../types/generated';
import type { AppData } from '../data';
import { createController, openReplay, readOnce, replayHref } from '../replay';
import type { Active, ControllerOptions, Opened } from '../replay';

const ROOT = 'https://snow.test/data/';

/** Lights for a made-up day: `n` schools closed. */
function lights(n: number): LitSchools {
  return {
    ...NOTHING_LIT,
    status: new Uint8Array(n),
    kinds: new Uint8Array(n),
    lngLat: new Float64Array(n * 2),
    schools: new Set(Array.from({ length: n }, (_, i) => i)),
    ids: Array.from({ length: n }, (_, i) => String(i)),
    names: Array.from({ length: n }, () => ''),
  };
}

function opened(day: LocalDate, n: number): Opened {
  return { day, lit: lights(n), lookup: () => null };
}

/** A tab's history, as the browser keeps it, with Back and Forward. */
class FakeTab extends EventTarget {
  entries: string[];
  index = 0;
  constructor(url: string) {
    super();
    this.entries = [url];
  }
  get location(): Location {
    return { href: this.entries[this.index] ?? '' } as Location;
  }
  readonly history = ((tab: FakeTab) =>
    ({
      state: null,
      pushState(_state: unknown, _unused: string, url?: string | URL | null): void {
        tab.entries.splice(tab.index + 1, Infinity, String(url));
        tab.index += 1;
      },
      replaceState(_state: unknown, _unused: string, url?: string | URL | null): void {
        tab.entries[tab.index] = String(url);
      },
    }) as unknown as History)(this);
  back(): void {
    this.index -= 1;
    this.dispatchEvent(new Event('popstate'));
  }
  forward(): void {
    this.index += 1;
    this.dispatchEvent(new Event('popstate'));
  }
  get search(): string {
    return new URL(this.location.href).search;
  }
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await new Promise((resolve) => setTimeout(resolve, 0));
}

/** A controller over a fake tab: what it held, lit, counted and told, in order. */
function control(open: ControllerOptions['open'], url = 'https://snow.test/?school=A1') {
  const tab = new FakeTab(url);
  const events: string[] = [];
  const painted: LitSchools[] = [];
  const glow = Promise.resolve({
    light: (lit: LitSchools) => painted.push(lit),
  } as unknown as Glow);
  const counts: [LocalDate, StatusCounts | null][] = [];
  const replays: (Active | null)[] = [];
  const controller = createController({
    hold: (held) => events.push(held ? 'hold' : 'release'),
    glow,
    filter: () => SHOW_ALL,
    open,
    onCounts: (day, next) => {
      events.push('counts');
      counts.push([day, next]);
    },
    onUpdated: () => events.push('updated'),
    onReplay: (active) => {
      events.push(active === null ? 'live' : `replay ${active.day}`);
      replays.push(active);
    },
    host: tab,
  });
  // The page passes Back and Forward on (app/boot.ts).
  tab.addEventListener('popstate', () => {
    controller.sync();
  });
  return { tab, events, painted, counts, replays, controller };
}

describe('entering a replay', () => {
  it('changes nothing until the day is read, then switches in one go and adds one history entry', async () => {
    let resolve: (value: Opened | null) => void = () => undefined;
    const { tab, events, painted, controller } = control(
      () => new Promise((done) => (resolve = done)),
    );
    const entering = controller.enter('2026-01-05', 'push');
    await settle();
    expect(events).toEqual([]);
    expect(tab.entries).toHaveLength(1);
    resolve(opened('2026-01-05', 3));
    expect(await entering).toBe(true);
    expect(events).toEqual(['hold', 'updated', 'counts', 'replay 2026-01-05']);
    expect(tab.entries).toHaveLength(2);
    expect(tab.search).toBe('?school=A1&replay=2026-01-05');
    await settle();
    expect(painted.map((lit) => lit.status.length)).toEqual([3]);
    expect(controller.active?.day).toBe('2026-01-05');
  });

  it('ends in the last day asked for: A, B, A', async () => {
    const waits: ((value: Opened | null) => void)[] = [];
    const { controller, replays, tab } = control(
      (day) =>
        new Promise((done) => {
          waits.push(() => {
            done(opened(day, day === '2026-01-05' ? 1 : 2));
          });
        }),
    );
    const a = controller.enter('2026-01-05', 'push');
    const b = controller.enter('2026-01-06', 'push');
    const again = controller.enter('2026-01-05', 'push');
    // They come back in reverse: only the last asked for counts.
    waits[2]?.(null);
    waits[1]?.(null);
    waits[0]?.(null);
    expect(await Promise.all([a, b, again])).toEqual([false, false, true]);
    expect(replays.map((active) => active?.day)).toEqual(['2026-01-05']);
    expect(tab.entries).toHaveLength(2);
  });

  it('enter, exit, then the read comes back: live it stays', async () => {
    let resolve: (value: Opened | null) => void = () => undefined;
    const { controller, events, painted, tab } = control(
      () => new Promise((done) => (resolve = done)),
    );
    const entering = controller.enter('2026-01-05', 'push');
    controller.exit('push');
    resolve(opened('2026-01-05', 3));
    expect(await entering).toBe(false);
    await settle();
    expect(events).toEqual(['release']);
    expect(painted).toEqual([]);
    expect(controller.active).toBeNull();
    expect(tab.entries).toHaveLength(1);
  });

  it('stays in the mode it is in when a day cannot be shown, and lets go of a held live', async () => {
    const { controller, events, tab } = control(() => Promise.resolve(null));
    expect(await controller.enter('2026-01-05', 'push')).toBe(false);
    expect(events).toEqual(['release']);
    expect(tab.entries).toHaveLength(1);
  });

  it("strips a link's day that cannot be shown, with no new entry", async () => {
    const { controller, tab } = control(
      () => Promise.resolve(null),
      'https://snow.test/?replay=1999-01-01&school=A1',
    );
    expect(await controller.enter('1999-01-01', 'boot')).toBe(false);
    expect(tab.entries).toEqual(['https://snow.test/?school=A1']);
  });

  it('a replay never paints after leaving it, and its counts name its day', async () => {
    let arrive: (glow: Glow) => void = () => undefined;
    const painted: LitSchools[] = [];
    const counts: LocalDate[] = [];
    const controller = createController({
      hold: () => undefined,
      glow: new Promise((done) => (arrive = done)),
      filter: () => SHOW_ALL,
      open: (day) => Promise.resolve(opened(day, 2)),
      onCounts: (day) => counts.push(day),
      onUpdated: () => undefined,
      onReplay: () => undefined,
      host: new FakeTab('https://snow.test/'),
    });
    await controller.enter('2026-01-05', 'push');
    controller.exit('push');
    arrive({ light: (lit: LitSchools) => painted.push(lit) } as unknown as Glow);
    await settle();
    expect(painted).toEqual([]);
    expect(counts).toEqual(['2026-01-05']);
  });
});

describe('leaving a replay, and history', () => {
  it('Back to live, then Back and Forward move between live and the replay with no new entry', async () => {
    const { controller, tab, events } = control((day) => Promise.resolve(opened(day, 3)));
    await controller.enter('2026-01-05', 'push');
    controller.exit('push');
    expect(tab.entries.map((url) => new URL(url).search)).toEqual([
      '?school=A1',
      '?school=A1&replay=2026-01-05',
      '?school=A1',
    ]);
    expect(events.slice(-2)).toEqual(['live', 'release']);
    tab.back();
    await settle();
    expect(controller.active?.day).toBe('2026-01-05');
    tab.back();
    await settle();
    expect(controller.active).toBeNull();
    tab.forward();
    await settle();
    expect(controller.active?.day).toBe('2026-01-05');
    expect(tab.entries).toHaveLength(3);
  });

  it('Back or Forward onto a day that cannot be shown puts the address back to what is shown', async () => {
    let fails = false;
    const { controller, tab } = control((day) => Promise.resolve(fails ? null : opened(day, 3)));
    await controller.enter('2026-01-05', 'push');
    controller.exit('push');
    // Offline now, or dropped by a later deploy: Back lands on the day's entry, live stays.
    fails = true;
    tab.back();
    await settle();
    expect(controller.active).toBeNull();
    expect(tab.search).toBe('?school=A1');
    expect(tab.entries).toHaveLength(3);
    // On a day, Back or Forward onto another that cannot be shown: the address keeps the day on.
    fails = false;
    await controller.enter('2026-01-06', 'push');
    fails = true;
    tab.entries[tab.index - 1] = 'https://snow.test/?school=A1&replay=2026-01-07';
    tab.back();
    await settle();
    expect(controller.active?.day).toBe('2026-01-06');
    expect(tab.search).toBe('?school=A1&replay=2026-01-06');
  });

  it('warms a day with nothing on screen changed', async () => {
    const open = vi.fn((day: LocalDate) => Promise.resolve(opened(day, 3)));
    const { controller, events, tab } = control(open);
    expect(await controller.warm('2026-01-05')).toBe(true);
    await settle();
    expect(open).toHaveBeenCalledWith('2026-01-05');
    expect(events).toEqual([]);
    expect(tab.entries).toHaveLength(1);
    expect(controller.active).toBeNull();
  });

  it('counts what the filter keeps as it changes', async () => {
    const { controller, counts } = control((day) => Promise.resolve(opened(day, 3)));
    await controller.enter('2026-01-05', 'push');
    controller.filter({ ...SHOW_ALL, public: false });
    expect(counts.map(([, next]) => next)).toEqual([
      [3, 0, 0, 0],
      [0, 0, 0, 0],
    ]);
  });

  it('writes only replay= into the address, and keeps everything else', () => {
    expect(replayHref('https://snow.test/?school=A1&at=39,-94,10#x', '2026-01-05')).toBe(
      'https://snow.test/?school=A1&at=39%2C-94%2C10&replay=2026-01-05#x',
    );
    expect(replayHref('https://snow.test/?replay=2026-01-05&zip=64112', null)).toBe(
      'https://snow.test/?zip=64112',
    );
  });
});

describe('openReplay', () => {
  const SCHOOLS = [
    { id: '010000500870', name: 'First', lon: -86.8, lat: 33.5, district: -1 },
    { id: '010000500871', name: 'Second', lon: -86.6, lat: 33.7, district: -1 },
  ];
  const META = testMeta(SCHOOLS);
  const POINTS = parsePoints(testPoints(SCHOOLS, 0), META);
  if (POINTS === null) throw new Error('points did not parse');
  const DIRECTORY = createDirectory(META, POINTS);
  const AFTER = new Date('2026-01-07T15:00:00Z');

  function withReplay(): AppData {
    const source: DirectorySource = { get: () => Promise.resolve(DIRECTORY) };
    return {
      files: createDataFiles(
        ['replays/2026-01-05.0123456789.json', 'schools/meta.json', 'schools/points.bin'],
        ROOT,
      ),
      directories: () => Promise.resolve(source),
    };
  }
  const serve = (value: unknown) => vi.fn(() => Promise.resolve(jsonResponse(value)));

  it('reads the day under its published name and lights it', async () => {
    const fetch = serve(testReplay('2026-01-05', META, [[1, 2, 0]]));
    const found = await openReplay(withReplay(), '2026-01-05', AFTER, fetch);
    expect(fetch).toHaveBeenCalledWith(`${ROOT}replays/2026-01-05.0123456789.json`, {});
    expect([...(found?.lit.schools ?? [])]).toEqual([1]);
    expect(found?.lookup('010000500871')).toEqual({ status: 2, reason: 0 });
  });

  it.each([
    ['a day this build does not ship', '2026-01-06', testReplay('2026-01-06', META, [[1, 0, 0]])],
    ['a malformed day', '2026-1-5', null],
    ['a file for another day', '2026-01-05', testReplay('2026-01-04', META, [[1, 0, 0]])],
    ['a file that breaks its rules', '2026-01-05', { rows: [] }],
    [
      'a file stamped for another directory',
      '2026-01-05',
      {
        ...testReplay('2026-01-05', META, [[1, 0, 0]]),
        directory: { generated_on: '2025-09-01', schools: 2, districts: 0 },
      },
    ],
    ['a day that lights nothing', '2026-01-05', testReplay('2026-01-05', META, [])],
  ])('refuses %s', async (_name, day, value) => {
    expect(await openReplay(withReplay(), day, AFTER, serve(value))).toBeNull();
  });

  it('refuses a day not over everywhere in the US, and an unreachable file', async () => {
    const file = testReplay('2026-01-05', META, [[1, 0, 0]]);
    const evening = new Date('2026-01-06T05:00:00Z');
    expect(await openReplay(withReplay(), '2026-01-05', evening, serve(file))).toBeNull();
    const failing = vi.fn(() => Promise.resolve(new Response('', { status: 500 })));
    expect(await openReplay(withReplay(), '2026-01-05', AFTER, failing)).toBeNull();
  });
});

describe('readOnce', () => {
  it('reads a day shown once, and reads again one that could not be shown', async () => {
    let fail = true;
    const open = vi.fn((day: LocalDate) =>
      fail ? Promise.reject(new Error('offline')) : Promise.resolve(opened(day, 1)),
    );
    const read = readOnce(open);
    expect(await read('2026-01-05')).toBeNull();
    fail = false;
    const first = read('2026-01-05');
    // A warm and a press at once: one read.
    const again = read('2026-01-05');
    expect(await first).not.toBeNull();
    expect(await again).toBe(await first);
    expect(await read('2026-01-05')).toBe(await first);
    expect(open).toHaveBeenCalledTimes(2);
    const none = vi.fn(() => Promise.resolve(null));
    const readNone = readOnce(none);
    await readNone('2026-01-05');
    await readNone('2026-01-05');
    expect(none).toHaveBeenCalledTimes(2);
  });
});

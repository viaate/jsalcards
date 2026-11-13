import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  MISS_RUNS_MAX,
  advance,
  barOf,
  dayOf,
  dayStart,
  expected,
  missIn,
  shareOf,
  step,
  windowStart,
} from '../shared/history.ts';
import { DAY, PARTS, TICK } from '../shared/types.ts';
import type {
  DayRow,
  Incident,
  Miss,
  Part,
  Reading,
  Sample,
  State,
  Summary,
} from '../shared/types.ts';
import { simulate } from './fixtures/made-up.ts';

const T0 = Date.UTC(2026, 10, 10, 0, 0, 0) / 1000;
const OK: Record<Part, State> = { site: 'ok', closings: 'ok', chances: 'ok', accounts: 'ok' };

function sample(t: number, states: Partial<Record<Part, State>> = {}): Sample {
  const parts = {} as Record<Part, Reading>;
  for (const part of PARTS) {
    parts[part] = { s: states[part] ?? 'ok', code: 200, ms: 50, made: null, allow: 0, bytes: null };
  }
  return { t, parts };
}

/** A store in memory, stepped as the checker steps the real one. */
class Memory {
  first: number | null = null;
  days: DayRow[] = [];
  incidents: Incident[] = [];
  summary: Summary | null = null;
  private id = 1;

  take(t: number, states: Partial<Record<Part, State>> = {}): Summary {
    const stepped = step(
      { first: this.first, days: this.days, incidents: this.incidents },
      sample(t, states),
    );
    this.first = stepped.first;
    for (const add of stepped.add) {
      const row = this.days.find((r) => r.day === add.day && r.part === add.part);
      if (row) {
        row.ok += add.ok;
        row.late += add.late;
        row.down += add.down;
      } else this.days.push({ ...add });
    }
    for (const row of stepped.changed) {
      this.incidents = this.incidents.map((i) => (i.id === row.id ? row : i));
    }
    for (const row of stepped.opened) this.incidents.push({ ...row, id: this.id++ });
    this.summary = stepped.summary;
    return stepped.summary;
  }
}

test('a sample adds to its own UTC day, and unknown adds nothing', () => {
  const store = new Memory();
  store.take(T0 - TICK, { site: 'late', accounts: 'unknown' });
  const summary = store.take(T0, { site: 'down', accounts: 'unknown' });
  assert.equal(summary.from, dayOf(T0 - 89 * DAY));
  assert.deepEqual(summary.days.site.slice(-2), [
    [0, 1, 0],
    [0, 0, 1],
  ]);
  assert.deepEqual(summary.days.closings.slice(-2), [
    [1, 0, 0],
    [1, 0, 0],
  ]);
  assert.deepEqual(summary.days.accounts.slice(-2), [
    [0, 0, 0],
    [0, 0, 0],
  ]);
  assert.deepEqual(
    store.days.find((r) => r.part === 'accounts' && r.day === dayOf(T0)),
    {
      day: dayOf(T0),
      part: 'accounts',
      ok: 0,
      late: 0,
      down: 0,
    },
  );
  assert.equal(dayStart('2026-11-10'), T0);
  assert.equal(windowStart(T0 + 5000), T0 - 89 * DAY);
});

test('an incident is opened, worsens, and is closed by a working reading', () => {
  const store = new Memory();
  store.take(T0);
  store.take(T0 + 300, { closings: 'late' });
  assert.deepEqual(store.summary!.incidents, [
    { p: 'closings', k: 'late', s: T0 + 300, e: null, g: 0, l: T0 + 300 },
  ]);
  store.take(T0 + 600, { closings: 'down' });
  store.take(T0 + 900, { closings: 'late' });
  // The worst state in it stays.
  assert.deepEqual(store.summary!.incidents, [
    { p: 'closings', k: 'down', s: T0 + 300, e: null, g: 0, l: T0 + 900 },
  ]);
  store.take(T0 + 1200);
  assert.deepEqual(store.summary!.incidents, [
    { p: 'closings', k: 'down', s: T0 + 300, e: T0 + 1200, g: 0 },
  ]);
  assert.equal(store.incidents.length, 1);
});

test('one bad sample is a 5-minute problem', () => {
  const store = new Memory();
  store.take(T0, { site: 'down' });
  const summary = store.take(T0 + 300);
  assert.deepEqual(summary.incidents, [{ p: 'site', k: 'down', s: T0, e: T0 + 300, g: 0 }]);
});

test('unknown and missing ticks neither open nor close', () => {
  const store = new Memory();
  store.take(T0, { chances: 'unknown' });
  assert.deepEqual(store.summary!.incidents, []);
  store.take(T0 + 300, { chances: 'late' });
  store.take(T0 + 600, { chances: 'unknown' });
  assert.deepEqual(store.summary!.incidents, [
    { p: 'chances', k: 'late', s: T0 + 300, e: null, g: 0, l: T0 + 300 },
  ]);
  // A tick is missing, then it is bad again 900 s after its last bad reading: the same problem.
  const later = store.take(T0 + 1200, { chances: 'late' });
  assert.deepEqual(later.incidents, [
    { p: 'chances', k: 'late', s: T0 + 300, e: null, g: 0, l: T0 + 1200 },
  ]);
});

test('more than 15 minutes with no known reading ends it where the readings stopped', () => {
  const store = new Memory();
  store.take(T0, { site: 'down' });
  store.take(T0 + 300, { site: 'down' });
  // 20 minutes later, bad again: the old one closes by gap and a new one opens.
  const summary = store.take(T0 + 1500, { site: 'late' });
  assert.deepEqual(summary.incidents, [
    { p: 'site', k: 'late', s: T0 + 1500, e: null, g: 0, l: T0 + 1500 },
    { p: 'site', k: 'down', s: T0, e: T0 + 600, g: 1 },
  ]);
  // The same by unknown readings, and then a working one: closed by gap, not at the ok.
  const other = new Memory();
  other.take(T0, { accounts: 'down' });
  for (let t = T0 + 300; t <= T0 + 900; t += 300) other.take(t, { accounts: 'unknown' });
  assert.equal(other.summary!.incidents[0]!.e, null);
  other.take(T0 + 1200, { accounts: 'unknown' });
  assert.deepEqual(other.summary!.incidents, [
    { p: 'accounts', k: 'down', s: T0, e: T0 + 300, g: 1 },
  ]);
  const third = new Memory();
  third.take(T0, { accounts: 'down' });
  third.take(T0 + 1200);
  assert.deepEqual(third.summary!.incidents, [
    { p: 'accounts', k: 'down', s: T0, e: T0 + 300, g: 1 },
  ]);
});

test('the summary lists open problems first, then the newest, 100 at most', () => {
  const store = new Memory();
  for (let i = 0; i < 120; i += 1) {
    store.take(T0 + i * 600, { site: 'down' });
    store.take(T0 + i * 600 + 300);
  }
  const summary = store.take(T0 + 120 * 600, { accounts: 'late', closings: 'late' });
  assert.equal(summary.incidents.length, 100);
  assert.deepEqual(
    summary.incidents.slice(0, 3).map((i) => [i.p, i.e]),
    [
      ['closings', null],
      ['accounts', null],
      ['site', T0 + 119 * 600 + 300],
    ],
  );
  assert.equal(summary.incidents[99]!.s, T0 + 22 * 600);
  assert.deepEqual(Object.keys(summary), [
    'v',
    'now',
    'first',
    'parts',
    'from',
    'days',
    'incidents',
    'miss',
  ]);
});

test('exactly 90 days, and what is older leaves the summary', () => {
  const old: Incident = {
    id: 1,
    part: 'site',
    kind: 'down',
    start: T0 - 95 * DAY,
    last: T0 - 95 * DAY,
    ended: T0 - 89 * DAY - 1,
    gap: 0,
  };
  const edge: Incident = { ...old, id: 2, ended: T0 - 89 * DAY };
  const days: DayRow[] = [
    { day: dayOf(T0 - 90 * DAY), part: 'site', ok: 5, late: 0, down: 0 },
    { day: dayOf(T0 - 89 * DAY), part: 'site', ok: 7, late: 0, down: 0 },
  ];
  const summary = step(
    { first: T0 - 200 * DAY, days, incidents: [old, edge] },
    sample(T0 + 600),
  ).summary;
  for (const part of PARTS) assert.equal(summary.days[part].length, 90);
  assert.deepEqual(summary.days.site[0], [7, 0, 0]);
  assert.deepEqual(summary.days.site[89], [1, 0, 0]);
  assert.deepEqual(
    summary.incidents.map((i) => i.e),
    [T0 - 89 * DAY],
  );
  assert.equal(summary.first, T0 - 200 * DAY);
  // `advance` alone gives the rows and no summary.
  assert.deepEqual(Object.keys(advance({ first: null, days: [], incidents: [] }, sample(T0))), [
    'first',
    'add',
    'opened',
    'changed',
    'miss',
  ]);
});

test('how many ticks a day should hold', () => {
  assert.equal(expected(T0, T0 - 5 * DAY, T0 + 5 * DAY), 288);
  assert.equal(expected(T0, T0, T0), 1);
  assert.equal(expected(T0, T0 + 300, T0 + 900), 3);
  assert.equal(expected(T0, T0 - DAY, T0 + 86100), 288);
  assert.equal(expected(T0, T0 + DAY, T0 + 2 * DAY), 0);
  assert.equal(expected(T0, T0 - 2 * DAY, T0 - 300), 0);
  assert.equal(expected(T0, T0 + 43200, T0 + 5 * DAY), 144);
});

test('every bar class, and a gap is never drawn as working', () => {
  assert.deepEqual(barOf([0, 0, 0], 0), { cls: 'before', e: 0, k: 0, m: 0 });
  assert.deepEqual(barOf([0, 0, 0], 288), { cls: 'none', e: 288, k: 0, m: 288 });
  assert.equal(barOf([287, 0, 1], 288).cls, 'down');
  assert.equal(barOf([280, 8, 0], 288).cls, 'late');
  assert.equal(barOf([200, 8, 1], 288).cls, 'down');
  assert.equal(barOf([288, 0, 0], 288).cls, 'ok');
  // The half-day rule: under half the day's readings is no readings, half is working.
  assert.deepEqual(barOf([144, 0, 0], 288), { cls: 'ok', e: 288, k: 144, m: 144 });
  assert.equal(barOf([143, 0, 0], 288).cls, 'none');
  // Trouble is shown even on a day with few readings.
  assert.equal(barOf([3, 1, 0], 288).cls, 'late');
  assert.equal(barOf([5, 0, 0], 3).m, 0);
});

test('the share of checks that found it working', () => {
  const full = (n: number): number[] => Array.from({ length: n }, () => 288);
  assert.deepEqual(
    shareOf(
      [
        [288, 0, 0],
        [288, 0, 0],
      ],
      full(2),
    ),
    { pct: '100%', days: 2 },
  );
  // 99.99% is not 100%: it shows 99.9.
  assert.deepEqual(shareOf([[9999, 1, 0]], full(1)), { pct: '99.9%', days: 1 });
  assert.deepEqual(shareOf([[9999, 0, 1]], full(1)), { pct: '99.9%', days: 1 });
  assert.deepEqual(shareOf([[1, 1, 0]], full(1)), { pct: '50.0%', days: 1 });
  assert.deepEqual(shareOf([[0, 0, 5]], full(1)), { pct: '0.0%', days: 1 });
  assert.deepEqual(
    shareOf(
      [
        [0, 0, 0],
        [0, 0, 0],
      ],
      [0, 288],
    ),
    { pct: null, days: 1 },
  );
  // The days are the bars that could hold a reading, with or without one.
  assert.deepEqual(
    shareOf(
      [
        [0, 0, 0],
        [0, 0, 0],
        [288, 0, 0],
      ],
      [0, 288, 288],
    ),
    { pct: '100%', days: 2 },
  );
});

test('the made-up history runs on the real code', () => {
  const summary = simulate(T0, T0 + 3 * DAY, (t) =>
    t === T0 + DAY ? { ...OK, site: 'down' } : OK,
  );
  assert.deepEqual(summary.days.site.slice(-4), [
    [288, 0, 0],
    [287, 0, 1],
    [288, 0, 0],
    [1, 0, 0],
  ]);
  assert.deepEqual(summary.incidents, [
    { p: 'site', k: 'down', s: T0 + DAY, e: T0 + DAY + 300, g: 0 },
  ]);
});

test('the runs of checks with no answer: joined, kept 90 days, and at most so many', () => {
  const store = new Memory();
  // Not one check missing: no runs, exact from the first tick.
  store.take(T0);
  let miss = store.summary!.miss!;
  assert.deepEqual(miss, {
    since: T0,
    runs: { site: [], closings: [], chances: [], accounts: [] },
  });
  // Ticks not taken, then a part that could not be checked right after: one run each.
  let last = T0;
  const take = (t: number, states: Partial<Record<Part, State>> = {}): Miss => {
    const stepped = step({ first: T0, days: [], incidents: [], miss, last }, sample(t, states));
    last = t;
    miss = stepped.miss;
    return miss;
  };
  take(T0 + 3 * TICK);
  take(T0 + 4 * TICK, { chances: 'unknown' });
  assert.deepEqual(take(T0 + 5 * TICK).runs, {
    site: [[T0 + TICK, 2]],
    closings: [[T0 + TICK, 2]],
    chances: [
      [T0 + TICK, 2],
      [T0 + 4 * TICK, 1],
    ],
    accounts: [[T0 + TICK, 2]],
  });
  // A part that flaps for long keeps the newest runs only; `since` moves up past the rest.
  for (let k = 6; k < 6 + 2 * (MISS_RUNS_MAX + 5); k += 2) {
    take(T0 + k * TICK, { site: 'unknown' });
    take(T0 + (k + 1) * TICK);
  }
  assert.equal(miss.runs.site.length, MISS_RUNS_MAX);
  assert.equal(miss.since, miss.runs.site[0]![0] - TICK);
  assert.deepEqual(miss.runs.chances, []);
  // 90 days on, what is older than the window is gone.
  const later = T0 + 100 * DAY;
  take(later);
  assert.equal(miss.since, windowStart(later));
  assert.deepEqual(miss.runs.site, [[windowStart(later), (later - windowStart(later)) / TICK]]);
  // A stored summary's runs are read back, and anything else is none.
  assert.deepEqual(missIn(JSON.parse(JSON.stringify(miss))), miss);
  for (const bad of [null, 3, { since: 1 }, { since: 0, runs: { site: [[1, 1]] } }]) {
    assert.equal(missIn(bad), null);
  }
});

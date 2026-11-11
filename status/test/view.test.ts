import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CHANCES_DOWN,
  CHANCES_LATE,
  CLOSINGS_DOWN,
  CLOSINGS_LATE,
  judgeFile,
} from '../shared/judge.ts';
import { DAY, PARTS, TICK } from '../shared/types.ts';
import type { Part, State, Summary, SummaryIncident } from '../shared/types.ts';
import * as page from '../page/src/view.ts';
import { elapsed, listed, nextDelay, readAnswer } from '../page/src/view.ts';
import type { Input, View } from '../page/src/view.ts';
import { allOk, history, launch, simulate, worst } from './fixtures/made-up.ts';

/**
 * The words as a reader sees them: a no-break space as a space, the word joiner gone. Every
 * test but the ones on line breaks reads the page this way.
 */
function plain<T>(value: T): T {
  if (typeof value === 'string') {
    return value.replace(/[\u00a0\u202f]/g, ' ').replace(/\u2060/g, '') as unknown as T;
  }
  if (Array.isArray(value)) return value.map((item) => plain(item)) as unknown as T;
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, plain(item)]),
    ) as unknown as T;
  }
  return value;
}
const viewOf = (input: Input): View => plain(page.viewOf(input));
const ago = (seconds: number): string => plain(page.ago(seconds));
const dur = (seconds: number): string => plain(page.dur(seconds));

const ZONE = 'America/New_York';
/** Tue Nov 10 2026, 15:00 UTC (10:00 AM EST). */
const NOW = Date.UTC(2026, 10, 10, 15, 0, 0) / 1000;
const OK: Record<Part, State> = { site: 'ok', closings: 'ok', chances: 'ok', accounts: 'ok' };

function summaryWith(
  states: Partial<Record<Part, State>>,
  incidents: SummaryIncident[] = [],
): Summary {
  const base = simulate(NOW - 3 * DAY, NOW, () => OK);
  for (const part of PARTS) {
    const s = states[part] ?? 'ok';
    base.parts[part] = part === 'closings' || part === 'chances' ? { s, made: NOW - 240 } : { s };
  }
  base.incidents = incidents;
  return base;
}

function data(summary: Summary | null, more: Partial<Extract<Input, { kind: 'data' }>> = {}): View {
  return viewOf({
    kind: 'data',
    summary,
    clock: NOW + 130,
    kept: false,
    expanded: false,
    picked: null,
    zone: ZONE,
    ...more,
  });
}

test('while it waits, the same boxes say Checking', () => {
  const view = viewOf({ kind: 'wait' });
  assert.deepEqual(view.banner, {
    shape: 'wait',
    lead: ['Checking…'],
    more: null,
    stuck: 'This page did not finish loading. Reload it to try again.',
  });
  assert.deepEqual(
    view.parts.map((row) => [row.name, row.word, row.shape, row.updated]),
    [
      ['Website', 'Checking', 'wait', null],
      ['Live school closings', 'Checking', 'wait', null],
      ['Snow-day chances', 'Checking', 'wait', null],
      ['Accounts', 'Checking', 'wait', null],
    ],
  );
  assert.deepEqual(
    view.parts.map((row) => row.file),
    [false, true, true, false],
  );
  assert.deepEqual(
    view.history.map((block) => [block.share, block.note, block.hint, block.bars.length]),
    [
      ['', '', false, 90],
      ['', '', false, 90],
      ['', '', false, 90],
      ['', '', false, 90],
    ],
  );
  assert.equal(
    view.history.every((block) =>
      block.bars.every((bar) => bar.cls === 'wait' && bar.label === null),
    ),
    true,
  );
  assert.deepEqual(view.problems, {
    slots: [null, null, null],
    empty: null,
    button: null,
    expanded: false,
  });
});

test('before the first check, and when the status cannot be loaded', () => {
  const first = data(null);
  assert.deepEqual(first.banner, {
    shape: 'wait',
    lead: ['The first check is on its way.'],
    more: 'This page fills in within 5 minutes.',
    stuck: null,
  });
  assert.deepEqual(
    first.parts.map((row) => row.word),
    ['Checking', 'Checking', 'Checking', 'Checking'],
  );
  assert.deepEqual(
    first.history.map((block) => block.share),
    Array.from({ length: 4 }, () => 'No checks yet.'),
  );
  // The box under "Problems" is never left blank: blank would read as "there were none".
  assert.equal(first.problems.empty, 'No checks yet.');
  const unreachable = viewOf({ kind: 'unreachable' });
  assert.deepEqual(unreachable.banner, {
    shape: 'unknown',
    lead: ['We cannot load the status right now.'],
    more: 'This page tries again every minute.',
    stuck: null,
  });
  assert.deepEqual(
    unreachable.parts.map((row) => row.word),
    Array.from({ length: 4 }, () => 'Could not check'),
  );
  assert.deepEqual(
    unreachable.history.map((block) => block.share),
    Array.from({ length: 4 }, () => 'The history could not be loaded.'),
  );
  assert.equal(unreachable.problems.empty, 'The history could not be loaded.');
  // No bar has a name in either, so nothing invites a tap.
  for (const view of [first, unreachable]) {
    assert.deepEqual(
      view.history.map((block) => [block.note, block.hint]),
      Array.from({ length: 4 }, () => ['', false]),
    );
    assert.deepEqual(view.problems.slots, [null, null, null]);
  }
});

test("the line under a part's name says what the part is, never how it is doing", () => {
  const states: State[] = ['ok', 'late', 'down', 'unknown'];
  const views = [
    viewOf({ kind: 'wait' }),
    viewOf({ kind: 'unreachable' }),
    data(null),
    data(summaryWith({}), { clock: NOW + 3 * DAY }),
    ...states.map((s) => data(summaryWith({ site: s, closings: s, chances: s, accounts: s }))),
  ];
  for (const view of views) {
    assert.deepEqual(
      view.parts.map((row) => row.says),
      [
        'Opening snowlightmap.com.',
        'The closings and delays on the map.',
        'Each district’s chance of no school.',
        'Signing in and saved schools.',
      ],
    );
    // No verb that could claim health beside "Not working" or "Could not check".
    for (const row of view.parts)
      assert.equal(
        /\b(?:is|are|opens?|works?|working|up to date|fine|ok)\b/i.test(row.says),
        false,
      );
  }
});

test('the banner says the worst first', () => {
  assert.deepEqual(data(summaryWith({})).banner, {
    shape: 'ok',
    lead: ['Everything is working.'],
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  assert.deepEqual(data(summaryWith({ accounts: 'unknown' })).banner, {
    shape: 'unknown',
    lead: ['We could not check everything just now.'],
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  assert.deepEqual(data(summaryWith({ chances: 'late', accounts: 'unknown' })).banner.lead, [
    'Slow or late right now: Snow-day chances.',
  ]);
  assert.deepEqual(data(summaryWith({ site: 'late', chances: 'late' })).banner.lead, [
    'Slow or late right now: Website and Snow-day chances.',
  ]);
  const both = data(
    summaryWith({ site: 'down', closings: 'down', chances: 'down', accounts: 'late' }),
  );
  assert.deepEqual(both.banner, {
    shape: 'down',
    lead: [
      'Not working right now: Website, Live school closings and Snow-day chances.',
      'Slow or late right now: Accounts.',
    ],
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  assert.deepEqual(data(summaryWith({ closings: 'down' })).banner.lead, [
    'Not working right now: Live school closings.',
  ]);
  assert.deepEqual(
    both.parts.map((row) => [row.word, row.shape]),
    [
      ['Not working', 'down'],
      ['Not working', 'down'],
      ['Not working', 'down'],
      ['Slow or late', 'late'],
    ],
  );
  assert.equal(listed(['A']), 'A');
  // "and" is tied to the name before it, so it never starts a line or stands on its own.
  assert.equal(listed(['A', 'B']), 'A\u00a0and B');
  assert.equal(listed(['A', 'B', 'C']), 'A, B\u00a0and C');
  assert.equal(listed(['A', 'B', 'C', 'D']), 'A, B, C\u00a0and D');
});

test('a failed refresh keeps what is shown and says so', () => {
  const view = data(summaryWith({ chances: 'late' }), { kept: true, clock: NOW + 14 * 60 });
  assert.deepEqual(view.banner, {
    shape: 'late',
    lead: ['Slow or late right now: Snow-day chances.'],
    more: 'Could not refresh. This is the check from 14 minutes ago.',
    stuck: null,
  });
});

test('a file part says when it was updated, counted from its own stamp', () => {
  const view = data(summaryWith({ chances: 'down' }));
  assert.deepEqual(
    view.parts.map((row) => row.updated),
    [null, 'Updated 6 minutes ago.', 'Updated 6 minutes ago.', null],
  );
  const none = summaryWith({});
  none.parts.chances = { s: 'unknown' };
  assert.deepEqual(
    data(none).parts.map((row) => row.updated),
    [null, 'Updated 6 minutes ago.', null, null],
  );
});

test('an open problem whose part could not be checked just now counts only to its last reading', () => {
  const open: SummaryIncident = {
    p: 'chances',
    k: 'late',
    s: NOW - 3600,
    e: null,
    g: 0,
    l: NOW - 900,
  };
  const unknown = data(summaryWith({ chances: 'unknown' }, [open]), { clock: NOW + 600 });
  assert.deepEqual(unknown.problems.slots[0], {
    what: 'Snow-day chances: slow or late since Nov 10, 9:00 AM EST.',
    when: '50 minutes so far.',
  });
  // Seen late just now: the length runs to the page's clock.
  const late = data(summaryWith({ chances: 'late' }, [{ ...open, l: NOW }]), { clock: NOW + 600 });
  assert.equal(late.problems.slots[0]!.when, '1 hour 10 minutes so far.');
});

test('stale: after 900 s with no newer summary nothing is said to work', () => {
  const open: SummaryIncident = { p: 'chances', k: 'late', s: NOW - 3600, e: null, g: 0, l: NOW };
  const summary = summaryWith({ chances: 'late' }, [open]);
  const fresh = data(summary, { clock: NOW + 900 });
  assert.equal(fresh.banner.shape, 'late');
  assert.deepEqual(fresh.problems.slots[0], {
    what: 'Snow-day chances: slow or late since Nov 10, 9:00 AM EST.',
    when: '1 hour 15 minutes so far.',
  });
  for (const kept of [false, true]) {
    const stale = data(summary, { clock: NOW + 901, kept });
    assert.deepEqual(stale.banner, {
      shape: 'unknown',
      lead: ['We have no recent checks.'],
      more: 'The last check was 15 minutes ago.',
      stuck: null,
    });
    assert.deepEqual(
      stale.parts.map((row) => [row.word, row.updated]),
      Array.from({ length: 4 }, () => ['Could not check', null]),
    );
    // The open problem is drawn as one whose readings stopped, a tick after its last.
    assert.deepEqual(stale.problems.slots[0], {
      what: 'Snow-day chances: slow or late for at least 1 hour 5 minutes.',
      when: 'From Nov 10, 9:00 AM EST. Our checks stopped while it was going on.',
    });
    // History stays, and today's bar says the time since the last check.
    assert.equal(stale.history[0]!.share, 'Working in 100% of our checks over 3 days.');
    assert.equal(
      stale.history[0]!.bars[89]!.label,
      'Tue, Nov 10: working when checked; not checked for 15 minutes.',
    );
  }
  assert.equal(fresh.history[0]!.bars[89]!.label, 'Tue, Nov 10: working so far today.');
});

test('the day checks began is never said to be working all day', () => {
  const at = (iso: string): number => Date.parse(iso) / 1000;
  const first = at('2026-11-10T20:40:00Z');
  const last = (view: View, n: number): (string | null)[] =>
    view.history[0]!.bars.slice(-n).map((bar) => bar.label);
  // Clean from the first check on, read two days later.
  const clean = simulate(first, at('2026-11-12T09:00:00Z'), () => OK);
  assert.deepEqual(last(data(clean, { clock: clean.now + 130 }), 4), [
    'Mon, Nov 9: before checks began.',
    'Tue, Nov 10: working since checks began.',
    'Wed, Nov 11: working all day.',
    'Thu, Nov 12: working so far today.',
  ]);
  assert.deepEqual(
    data(clean, { clock: clean.now + 130 })
      .history[0]!.bars.slice(-4)
      .map((bar) => bar.cls),
    ['before', 'ok', 'ok', 'ok'],
  );
  // The same day while it is still today.
  const young = simulate(first, at('2026-11-10T22:00:00Z'), () => OK);
  assert.deepEqual(last(data(young, { clock: young.now + 130 }), 2), [
    'Mon, Nov 9: before checks began.',
    'Tue, Nov 10: working since checks began.',
  ]);
  // A later gap on that day: its time with no check is counted from the day's start
  // (20 h 40 min before the first check, and the 30 minutes missed).
  const gap = simulate(first, at('2026-11-11T09:00:00Z'), (t) =>
    t >= at('2026-11-10T22:00:00Z') && t < at('2026-11-10T22:30:00Z') ? null : OK,
  );
  assert.deepEqual(last(data(gap, { clock: gap.now + 130 }), 2), [
    'Tue, Nov 10: working when checked; not checked for 21 hours 10 minutes.',
    'Wed, Nov 11: working so far today.',
  ]);
  // Trouble on that day, with every check since the first kept.
  const bad = simulate(first, at('2026-11-11T09:00:00Z'), (t) =>
    t >= at('2026-11-10T21:00:00Z') && t < at('2026-11-10T22:00:00Z')
      ? { ...OK, site: 'down' }
      : OK,
  );
  assert.equal(
    data(bad, { clock: bad.now + 130 }).history[0]!.bars[88]!.label,
    'Tue, Nov 10: not working for 1 hour, not checked for 20 hours 40 minutes.',
  );
  // Checks that began on a day's first tick did check all of it.
  const whole = simulate(at('2026-11-10T00:00:00Z'), at('2026-11-11T09:00:00Z'), () => OK);
  assert.equal(
    data(whole, { clock: whole.now + 130 }).history[0]!.bars[88]!.label,
    'Tue, Nov 10: working all day.',
  );
});

test('"today" is the clock\'s day: an old summary never names its last day today', () => {
  const summary = summaryWith({});
  const tail = (view: View, n: number): [string, string | null][] =>
    view.history[0]!.bars.slice(-n).map((bar) => [bar.cls, bar.label]);
  // One day old: the checks stopped at 15:00 UTC on Nov 10, and nothing is known of Nov 11.
  const one = data(summary, { clock: NOW + DAY + 2 * 3600 });
  assert.equal(one.banner.more, 'The last check was 26 hours ago.');
  assert.deepEqual(tail(one, 3), [
    ['ok', 'Mon, Nov 9: working all day.'],
    ['ok', 'Tue, Nov 10: working when checked; not checked for 8 hours 55 minutes.'],
    ['none', 'Wed, Nov 11: not checked.'],
  ]);
  // Three days old: the bars moved up three days, so the last one is the clock's day.
  const three = data(summary, { clock: NOW + 3 * DAY + 2 * 3600 });
  assert.equal(three.banner.more, 'The last check was 3 days ago.');
  assert.deepEqual(tail(three, 5), [
    ['ok', 'Mon, Nov 9: working all day.'],
    ['ok', 'Tue, Nov 10: working when checked; not checked for 8 hours 55 minutes.'],
    ['none', 'Wed, Nov 11: not checked.'],
    ['none', 'Thu, Nov 12: not checked.'],
    ['none', 'Fri, Nov 13: not checked.'],
  ]);
  for (const view of [one, three]) {
    assert.equal(view.history[0]!.bars.length, 90);
    for (const block of view.history)
      for (const bar of block.bars) assert.equal(/today/i.test(bar.label ?? ''), false);
    // The share is of the checks that were made, over the whole days they span.
    assert.equal(view.history[0]!.share, 'Working in 100% of our checks over 3 days.');
  }
  // A picked bar is counted on the bars as drawn.
  assert.equal(
    data(summary, { clock: NOW + 3 * DAY, picked: { part: 'site', day: 86 } }).history[0]!.note,
    'Tue, Nov 10: working when checked; not checked for 8 hours 55 minutes.',
  );
  // Checks that stopped early in a day: under half of it was checked, so it is not drawn working.
  const early = simulate(NOW - 3 * DAY, NOW - 9 * 3600, () => OK);
  assert.deepEqual(tail(data(early, { clock: NOW + DAY }), 2), [
    ['none', 'Tue, Nov 10: working when checked; not checked for 17 hours 55 minutes.'],
    ['none', 'Wed, Nov 11: not checked.'],
  ]);
  // Older than the 90 days kept: nothing is left to draw as checked.
  const gone = data(summary, { clock: NOW + 200 * DAY });
  assert.equal(
    gone.history[0]!.bars.every((bar) => bar.cls === 'none'),
    true,
  );
  assert.equal(gone.history[0]!.bars.length, 90);
});

test('just after midnight the new day waits for its first check', () => {
  const midnight = Math.floor(NOW / DAY) * DAY;
  // The last tick of Nov 9 is in; the clock is two minutes into Nov 10.
  const summary = simulate(midnight - 2 * DAY, midnight - TICK, () => OK);
  const view = data(summary, { clock: midnight + 120 });
  assert.equal(view.banner.more, 'Last checked 7 minutes ago.');
  assert.deepEqual(
    view.history[0]!.bars.slice(-3).map((bar) => [bar.cls, bar.label]),
    [
      ['ok', 'Sun, Nov 8: working all day.'],
      ['ok', 'Mon, Nov 9: working all day.'],
      ['yet', 'Tue, Nov 10: not checked yet.'],
    ],
  );
  // The day before, with its last tick not in yet, is not said to be whole.
  const short = simulate(midnight - 2 * DAY, midnight - 2 * TICK, () => OK);
  assert.equal(
    data(short, { clock: midnight + 120 }).history[0]!.bars[88]!.label,
    'Mon, Nov 9: working when checked; not checked for 5 minutes.',
  );
  // With the first tick of the day in, it is today again.
  const next = simulate(midnight - 2 * DAY, midnight, () => OK);
  assert.equal(
    data(next, { clock: midnight + 120 }).history[0]!.bars[89]!.label,
    'Tue, Nov 10: working so far today.',
  );
});

test('the clock is the larger of the two differences', () => {
  const then = { perf: 5000, date: 1_800_000_000_000 };
  assert.equal(elapsed(then, { perf: 65000, date: 1_800_000_060_000 }), 60);
  // A device asleep 8 hours: its performance clock stood still.
  assert.equal(elapsed(then, { perf: 6000, date: 1_800_000_000_000 + 8 * 3600 * 1000 }), 8 * 3600);
  // A device clock set back an hour: the performance clock still counts.
  assert.equal(elapsed(then, { perf: 35000, date: 1_800_000_000_000 - 3600 * 1000 }), 30);
  assert.equal(elapsed(then, { perf: 4000, date: 1_799_999_999_000 }), 0);
});

test('when the page asks again', () => {
  const summary = summaryWith({});
  assert.equal(nextDelay(true, summary, NOW + 130), 215);
  assert.equal(nextDelay(true, summary, NOW), 345);
  assert.equal(nextDelay(true, summary, NOW - 60), 345);
  assert.equal(nextDelay(true, summary, NOW + 300), 60);
  assert.equal(nextDelay(true, summary, NOW + 900), 60);
  assert.equal(nextDelay(true, summary, NOW + 901), 300);
  assert.equal(nextDelay(true, null, NOW), 60);
  assert.equal(nextDelay(false, summary, NOW), 60);
});

test('an answer the page can draw', () => {
  const summary = summaryWith({});
  assert.deepEqual(readAnswer(200, { served: 5, summary: null }), { served: 5, summary: null });
  assert.deepEqual(readAnswer(200, { served: 5, summary }), { served: 5, summary });
  assert.equal(readAnswer(503, { served: 5, summary: null }), null);
  assert.equal(readAnswer(200, { served: '5', summary: null }), null);
  assert.equal(readAnswer(200, { summary: null }), null);
  assert.equal(readAnswer(200, { served: 5 }), null);
  assert.equal(readAnswer(200, { served: 5, summary: { ...summary, v: 2 } }), null);
  assert.equal(readAnswer(200, { served: 5, summary: 'x' }), null);
  assert.equal(readAnswer(200, null), null);
  assert.equal(readAnswer(200, 'ok'), null);
});

test('ago, at each boundary', () => {
  assert.equal(ago(-30), 'just now');
  assert.equal(ago(0), 'just now');
  assert.equal(ago(59), 'just now');
  assert.equal(ago(60), '1 minute ago');
  assert.equal(ago(119), '1 minute ago');
  assert.equal(ago(120), '2 minutes ago');
  assert.equal(ago(3599), '59 minutes ago');
  assert.equal(ago(3600), '1 hour ago');
  assert.equal(ago(7199), '1 hour ago');
  assert.equal(ago(7200), '2 hours ago');
  assert.equal(ago(48 * 3600 - 1), '47 hours ago');
  assert.equal(ago(48 * 3600), '2 days ago');
  assert.equal(ago(72 * 3600 - 1), '2 days ago');
  assert.equal(ago(90 * DAY), '90 days ago');
});

test('dur, at each boundary', () => {
  assert.equal(dur(0), '1 minute');
  assert.equal(dur(60), '1 minute');
  assert.equal(dur(300), '5 minutes');
  assert.equal(dur(3599), '59 minutes');
  assert.equal(dur(3600), '1 hour');
  assert.equal(dur(3660), '1 hour 1 minute');
  assert.equal(dur(3900), '1 hour 5 minutes');
  assert.equal(dur(7200), '2 hours');
  assert.equal(dur(6 * 3600), '6 hours');
  assert.equal(dur(48 * 3600 - 60), '47 hours 59 minutes');
  assert.equal(dur(48 * 3600), '2 days');
  assert.equal(dur(49 * 3600 + 59 * 60), '2 days 1 hour');
  assert.equal(dur(50 * 3600), '2 days 2 hours');
  assert.equal(dur(72 * 3600), '3 days');
});

test("a bar's name, for each class and for a gap", () => {
  const first = NOW - 5 * DAY - 15 * 3600 + 6 * 3600;
  const base = simulate(first, NOW, (t) => {
    const day = Math.floor(t / DAY) - Math.floor(NOW / DAY);
    if (day === -4) return t % DAY < 6 * 3600 ? null : OK;
    if (day === -3) return null;
    if (day === -2) {
      if (t % DAY < 3600) return { ...OK, site: 'down' };
      if (t % DAY < 3 * 3600) return { ...OK, site: 'late' };
      return t % DAY < 5 * 3600 ? null : OK;
    }
    if (day === -1) return t % DAY < 20 * 3600 ? null : OK;
    return OK;
  });
  const view = data(base, { picked: { part: 'site', day: 86 } });
  const site = view.history[0]!;
  assert.deepEqual(
    site.bars.slice(83).map((bar) => [bar.cls, bar.label]),
    [
      ['before', 'Wed, Nov 4: before checks began.'],
      // Checks began at 06:00 UTC that day: every check since then was kept.
      ['ok', 'Thu, Nov 5: working since checks began.'],
      ['ok', 'Fri, Nov 6: working when checked; not checked for 6 hours.'],
      ['none', 'Sat, Nov 7: not checked.'],
      [
        'down',
        'Sun, Nov 8: not working for 1 hour, slow or late for 2 hours, not checked for 2 hours.',
      ],
      // Under half the day's checks: drawn as not checked, never as working.
      ['none', 'Mon, Nov 9: working when checked; not checked for 20 hours.'],
      ['ok', 'Tue, Nov 10: working so far today.'],
    ],
  );
  assert.equal(site.note, 'Sat, Nov 7: not checked.');
  assert.equal(site.hint, false);
  assert.deepEqual(site.bars.map((bar) => bar.picked).indexOf(true), 86);
  // A block with no bar picked says how to pick one.
  assert.deepEqual(
    [view.history[1]!.note, view.history[1]!.hint],
    ['Pick a bar to see that day.', true],
  );
  // 889 of the 925 checks that gave a reading.
  assert.equal(site.share, 'Working in 96.1% of our checks over 5 days.');
  const late = simulate(NOW - DAY, NOW, (t) =>
    t === NOW - 600 ? { ...OK, accounts: 'late' } : OK,
  );
  assert.equal(data(late).history[3]!.bars[89]!.label, 'Tue, Nov 10: slow or late for 5 minutes.');
  assert.equal(data(late).history[3]!.bars[89]!.cls, 'late');
});

test('problems: closed, closed by a gap, open, and across a change of clocks', () => {
  const at = (iso: string): number => Date.parse(iso) / 1000;
  const incidents: SummaryIncident[] = [
    { p: 'chances', k: 'late', s: at('2026-11-10T13:55:00Z'), e: null, g: 0, l: NOW },
    {
      p: 'closings',
      k: 'down',
      s: at('2026-11-07T11:10:00Z'),
      e: at('2026-11-07T11:35:00Z'),
      g: 0,
    },
    {
      p: 'closings',
      k: 'down',
      s: at('2026-10-31T01:50:00Z'),
      e: at('2026-10-31T02:00:00Z'),
      g: 1,
    },
    // Clocks went back on Nov 1 2026 at 2 AM Eastern: this one began in EDT and ended in EST.
    { p: 'site', k: 'late', s: at('2026-11-01T04:30:00Z'), e: at('2026-11-01T07:15:00Z'), g: 0 },
    {
      p: 'accounts',
      k: 'down',
      s: at('2026-10-20T03:50:00Z'),
      e: at('2026-10-20T04:10:00Z'),
      g: 0,
    },
  ];
  const summary = summaryWith({ chances: 'late' }, incidents);
  const all = data(summary, { expanded: true, clock: NOW + 300 });
  assert.deepEqual(all.problems.slots, [
    {
      what: 'Snow-day chances: slow or late since Nov 10, 8:55 AM EST.',
      when: '1 hour 10 minutes so far.',
    },
    {
      what: 'Live school closings: not working for 25 minutes.',
      when: 'Nov 7, 6:10 AM to 6:35 AM EST',
    },
    {
      what: 'Live school closings: not working for at least 10 minutes.',
      when: 'From Oct 30, 9:50 PM EDT. Our checks stopped while it was going on.',
    },
    {
      what: 'Website: slow or late for 2 hours 45 minutes.',
      when: 'Nov 1, 12:30 AM EDT to 2:15 AM EST',
    },
    // It ended on another day: the end names its date.
    {
      what: 'Accounts: not working for 20 minutes.',
      when: 'Oct 19, 11:50 PM to Oct 20, 12:10 AM EDT',
    },
  ]);
  assert.equal(all.problems.button, 'Show fewer');
  assert.equal(all.problems.expanded, true);
  const some = data(summary);
  assert.equal(some.problems.slots.length, 3);
  assert.equal(some.problems.button, 'Show all 5');
  // Another reader's zone gives the same instants in their own clock.
  const utc = data(summary, { zone: 'UTC' });
  assert.equal(utc.problems.slots[1]!.when, 'Nov 7, 11:10 AM to 11:35 AM UTC');
});

test('the three slots with 0, 3 and 4 problems', () => {
  const one = (i: number): SummaryIncident => ({
    p: 'site',
    k: 'down',
    s: NOW - (i + 1) * DAY,
    e: NOW - (i + 1) * DAY + 300,
    g: 0,
  });
  const none = data(summaryWith({}));
  assert.deepEqual(none.problems, {
    slots: [null, null, null],
    empty: 'No problems since checks began on Nov 7.',
    button: null,
    expanded: false,
  });
  // Checks that began 90 days ago or more: the plain sentence.
  assert.equal(data(allOk(NOW)).problems.empty, 'No problems in the last 90 days.');
  const two = data(summaryWith({}, [one(0), one(1)]));
  assert.deepEqual(
    two.problems.slots.map((slot) => slot === null),
    [false, false, true],
  );
  assert.equal(two.problems.empty, null);
  const three = data(summaryWith({}, [one(0), one(1), one(2)]));
  assert.deepEqual([three.problems.slots.length, three.problems.button], [3, null]);
  const four = data(summaryWith({}, [one(0), one(1), one(2), one(3)]));
  assert.deepEqual([four.problems.slots.length, four.problems.button], [3, 'Show all 4']);
  const open = data(summaryWith({}, [one(0), one(1), one(2), one(3)]), { expanded: true });
  assert.deepEqual([open.problems.slots.length, open.problems.button], [4, 'Show fewer']);
});

test('a part no check could reach says so, and an old summary says nothing of the days since', () => {
  // Launch day: the chances' stamp is not on the host, so every check of them gave no answer.
  const first = data(launch(NOW));
  assert.deepEqual(first.banner.lead, ['We could not check everything just now.']);
  assert.deepEqual(
    first.history.map((block) => block.share),
    [
      'Working in 100% of our checks over 2 hours.',
      'Working in 100% of our checks over 2 hours.',
      'Could not check so far.',
      'Working in 100% of our checks over 2 hours.',
    ],
  );
  assert.equal(first.problems.empty, 'No problems since checks began on Nov 10.');
  // "No checks yet" is said before the first check only.
  assert.equal(JSON.stringify(first).includes('No checks yet'), false);

  // A quiet summary a day old: no problem is known, and nothing is said of the day since.
  const quiet = summaryWith({});
  const day = data(quiet, { clock: NOW + DAY });
  assert.equal(day.problems.empty, 'No problems up to the last check.');
  assert.equal(data(allOk(NOW), { clock: NOW + DAY }).problems.empty, day.problems.empty);
  // Not yet stale, and only the refresh failed: the summary's own sentence stands.
  assert.equal(
    data(quiet, { clock: NOW + 800, kept: true }).problems.empty,
    'No problems since checks began on Nov 7.',
  );

  // The list is of the 90 days the bars show. The made-up history has four problems: 20, 10
  // and 3 days back, and one open. Read 85 days late, the bars begin 4 days before its last
  // check, so the two older ones are gone and the open one ends where the checks stopped.
  const old = history(NOW);
  assert.equal(data(old, { expanded: true }).problems.slots.length, 4);
  const late = data(old, { clock: NOW + 85 * DAY, expanded: true });
  assert.equal(late.history[0]!.bars[0]!.label, 'Fri, Nov 6: working all day.');
  assert.deepEqual(late.problems.slots, [
    {
      what: 'Snow-day chances: slow or late for at least 1 hour 10 minutes.',
      when: 'From Nov 10, 8:55 AM EST. Our checks stopped while it was going on.',
    },
    {
      what: 'Live school closings: not working for 25 minutes.',
      when: 'Nov 7, 6:10 AM to 6:35 AM EST',
    },
    null,
  ]);
  assert.equal(late.problems.button, null);

  // 100 days late: no day shown was checked. Each bar is a day of the clock's own 90, the
  // last one the clock's day; nothing is listed; and the lines say why, not "No checks yet".
  const gone = data(old, { clock: NOW + 100 * DAY, expanded: true });
  assert.deepEqual(gone.banner.lead, ['We have no recent checks.']);
  assert.deepEqual(
    gone.history.map((block) => block.share),
    Array.from({ length: 4 }, () => 'Not checked in the last 90 days.'),
  );
  assert.deepEqual(gone.problems, {
    slots: [null, null, null],
    empty: 'Not checked in the last 90 days.',
    button: null,
    expanded: true,
  });
  const bars = gone.history[0]!.bars;
  assert.deepEqual(
    [bars[0]!.label, bars[89]!.label],
    ['Sat, Nov 21: not checked.', 'Thu, Feb 18: not checked.'],
  );
  assert.equal(
    bars.every((bar) => bar.cls === 'none'),
    true,
  );
  // 89 days late: the summary's last day is still the first bar.
  const edge = data(old, { clock: NOW + 89 * DAY });
  assert.equal(
    edge.history[0]!.bars[0]!.label,
    'Tue, Nov 10: working when checked; not checked for 8 hours 55 minutes.',
  );
  // Its checks shown span the 15 hours from the first bar's start to the last check.
  assert.equal(edge.history[0]!.share, 'Working in 100% of our checks over 15 hours.');
});

test('the share never names more time than its checks span', () => {
  const first = Date.UTC(2026, 10, 10, 18, 0, 0) / 1000;
  const share = (hours: number): string => {
    const now = first + Math.round(hours * 60) * 60;
    return data(
      simulate(first, now, () => OK),
      { clock: now + 60 },
    ).history[0]!.share;
  };
  assert.equal(share(23 + 55 / 60), 'Working in 100% of our checks over 23 hours 55 minutes.');
  // A day of checks is drawn on two bars, and is still one day.
  assert.equal(share(24), 'Working in 100% of our checks over 1 day.');
  assert.equal(share(25), 'Working in 100% of our checks over 1 day.');
  assert.equal(share(47.9), 'Working in 100% of our checks over 1 day.');
  assert.equal(share(48), 'Working in 100% of our checks over 2 days.');
  // Older than the bars: the 90 days they show, as before.
  assert.equal(share(100 * 24), 'Working in 100% of our checks over 89 days.');
});

test('a day whose first check is not due has a bar of its own kind', () => {
  const midnight = Math.floor(NOW / DAY) * DAY;
  const eve = simulate(midnight - 2 * DAY, midnight - 300, () => OK);
  const classes = (clock: number): string[] =>
    data(eve, { clock }).history.map((block) => block.bars[89]!.cls);
  // The clock is in the new day and the last check, 23:55, is not old: nothing is drawn yet.
  assert.deepEqual(classes(midnight + 100), ['yet', 'yet', 'yet', 'yet']);
  assert.deepEqual(classes(midnight + 599), ['yet', 'yet', 'yet', 'yet']);
  // Once that check is old the day's checks are counted to the clock: it was not checked.
  assert.deepEqual(classes(midnight + 601), ['none', 'none', 'none', 'none']);
  assert.equal(
    data(eve, { clock: midnight + 601 }).history[0]!.bars[89]!.label,
    'Tue, Nov 10: not checked.',
  );
  // A day before the checks began keeps its own kind.
  assert.equal(data(eve, { clock: midnight + 100 }).history[0]!.bars[86]!.cls, 'before');
});

test('the made-up history reads as the pictures show it', () => {
  const view = data(history(NOW), { clock: NOW + 130 });
  assert.deepEqual(view.banner.lead, ['Slow or late right now: Snow-day chances.']);
  assert.equal(view.history[0]!.bars.filter((bar) => bar.cls === 'before').length, 30);
  assert.equal(
    view.history[1]!.bars[79]!.label,
    'Sat, Oct 31: not working for 15 minutes, not checked for 6 hours.',
  );
  assert.equal(view.history[3]!.share, 'Working in 100% of our checks over 59 days.');
  assert.equal(view.problems.button, 'Show all 4');
});

test('a made-up file part is as old as the real judge needs for its state', () => {
  const limits = {
    closings: [CLOSINGS_LATE, CLOSINGS_DOWN],
    chances: [CHANCES_LATE, CHANCES_DOWN],
  } as const;
  let seen = 0;
  for (const summary of [history(NOW), worst(NOW), allOk(NOW), summaryFrom()]) {
    for (const part of ['closings', 'chances'] as const) {
      const { s, made } = summary.parts[part];
      assert.notEqual(made, undefined);
      const age = summary.now - made!;
      const [late, down] = limits[part];
      const wanted: State = age > down ? 'down' : age > late ? 'late' : 'ok';
      assert.equal(s, wanted, `${part} ${s} at ${age} s`);
      // And by the judge itself, from a stamp of that age.
      const generated_at = new Date(made! * 1000).toISOString().replace('.000Z', 'Z');
      const body = new TextEncoder().encode(
        JSON.stringify(part === 'closings' ? { generated_at } : { generated_at, districts: 9 }),
      );
      assert.equal(judgeFile(part, { code: 200, age: null, body, now: summary.now }).s, s);
      seen += 1;
    }
  }
  assert.equal(seen, 8);
  // The pictures' two troubled files: late for an hour, and down for days.
  assert.equal(data(history(NOW)).parts[2]!.updated, 'Updated 1 hour ago.');
  assert.deepEqual(
    data(worst(NOW)).parts.map((row) => [row.word, row.updated]),
    [
      ['Not working', null],
      // Late for a day before it stopped: its file is older than the outage.
      ['Not working', 'Updated 3 days ago.'],
      ['Not working', 'Updated 2 days ago.'],
      ['Slow or late', null],
    ],
  );
});

/** A made-up run where both files go late, then down, and are read while down. */
function summaryFrom(): Summary {
  return simulate(NOW - DAY, NOW, (t) => {
    if (t >= NOW - 3600) return { ...OK, closings: 'down', chances: 'down' };
    if (t >= NOW - 7200) return { ...OK, closings: 'late', chances: 'late' };
    return OK;
  });
}

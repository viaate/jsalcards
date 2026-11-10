import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DAY, PARTS } from '../shared/types.ts';
import type { Part, State, Summary, SummaryIncident } from '../shared/types.ts';
import { ago, dur, elapsed, listed, nextDelay, readAnswer, viewOf } from '../page/src/view.ts';
import type { Input, View } from '../page/src/view.ts';
import { allOk, history, simulate } from './fixtures/made-up.ts';

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
  assert.deepEqual(view.banner, { shape: 'wait', lead: ['Checking…'], more: null });
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
    view.history.map((block) => [block.share, block.note, block.bars.length]),
    [
      ['', '', 90],
      ['', '', 90],
      ['', '', 90],
      ['', '', 90],
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
  });
  assert.deepEqual(
    first.parts.map((row) => row.word),
    ['Checking', 'Checking', 'Checking', 'Checking'],
  );
  assert.deepEqual(
    first.history.map((block) => block.share),
    Array.from({ length: 4 }, () => 'No readings yet.'),
  );
  assert.equal(first.problems.empty, null);
  const unreachable = viewOf({ kind: 'unreachable' });
  assert.deepEqual(unreachable.banner, {
    shape: 'unknown',
    lead: ['We cannot load the status right now.'],
    more: 'This page tries again every minute.',
  });
  assert.deepEqual(
    unreachable.parts.map((row) => row.word),
    Array.from({ length: 4 }, () => 'Could not check'),
  );
});

test('the banner says the worst first', () => {
  assert.deepEqual(data(summaryWith({})).banner, {
    shape: 'ok',
    lead: ['Everything is working.'],
    more: 'Last checked 2 minutes ago.',
  });
  assert.deepEqual(data(summaryWith({ accounts: 'unknown' })).banner, {
    shape: 'unknown',
    lead: ['We could not check everything just now.'],
    more: 'Last checked 2 minutes ago.',
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
  assert.equal(listed(['A', 'B']), 'A and B');
  assert.equal(listed(['A', 'B', 'C']), 'A, B and C');
  assert.equal(listed(['A', 'B', 'C', 'D']), 'A, B, C and D');
});

test('a failed refresh keeps what is shown and says so', () => {
  const view = data(summaryWith({ chances: 'late' }), { kept: true, clock: NOW + 14 * 60 });
  assert.deepEqual(view.banner, {
    shape: 'late',
    lead: ['Slow or late right now: Snow-day chances.'],
    more: 'Could not refresh. This is the check from 14 minutes ago.',
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
      lead: ['We have no fresh readings.'],
      more: 'The last check was 15 minutes ago. Everything below is from then.',
    });
    assert.deepEqual(
      stale.parts.map((row) => [row.word, row.updated]),
      Array.from({ length: 4 }, () => ['Could not check', null]),
    );
    // The open problem is drawn as one whose readings stopped, a tick after its last.
    assert.deepEqual(stale.problems.slots[0], {
      what: 'Snow-day chances: slow or late for at least 1 hour 5 minutes.',
      when: 'From Nov 10, 9:00 AM EST. Our readings stopped while it was going on.',
    });
    // History stays.
    assert.equal(stale.history[0]!.share, 'Working in 100% of our checks over 4 days.');
  }
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
      ['ok', 'Thu, Nov 5: working all day.'],
      ['ok', 'Fri, Nov 6: working when checked; no readings for 6 hours.'],
      ['none', 'Sat, Nov 7: no readings.'],
      [
        'down',
        'Sun, Nov 8: not working for 1 hour, slow or late for 2 hours, no readings for 2 hours.',
      ],
      // Under half the day's readings: drawn as no readings, never as working.
      ['none', 'Mon, Nov 9: working when checked; no readings for 20 hours.'],
      ['ok', 'Tue, Nov 10: working so far today.'],
    ],
  );
  assert.equal(site.note, 'Sat, Nov 7: no readings.');
  assert.deepEqual(site.bars.map((bar) => bar.picked).indexOf(true), 86);
  assert.equal(view.history[1]!.note, '');
  // 889 of the 925 checks that gave a reading.
  assert.equal(site.share, 'Working in 96.1% of our checks over 6 days.');
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
      when: 'From Oct 30, 9:50 PM EDT. Our readings stopped while it was going on.',
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

test('the made-up history reads as the pictures show it', () => {
  const view = data(history(NOW), { clock: NOW + 130 });
  assert.deepEqual(view.banner.lead, ['Slow or late right now: Snow-day chances.']);
  assert.equal(view.history[0]!.bars.filter((bar) => bar.cls === 'before').length, 30);
  assert.equal(
    view.history[1]!.bars[79]!.label,
    'Sat, Oct 31: not working for 15 minutes, no readings for 6 hours.',
  );
  assert.equal(view.history[3]!.share, 'Working in 100% of our checks over 60 days.');
  assert.equal(view.problems.button, 'Show all 4');
});

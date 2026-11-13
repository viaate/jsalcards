import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CHANCES_DOWN,
  CHANCES_LATE,
  CLOSINGS_DOWN,
  CLOSINGS_LATE,
  judgeFile,
} from '../shared/judge.ts';
import { INCIDENTS_MAX } from '../shared/history.ts';
import { DAY, PARTS, TICK } from '../shared/types.ts';
import type { Part, State, Summary, SummaryIncident } from '../shared/types.ts';
import * as page from '../page/src/view.ts';
import { elapsed, listed, nextDelay, readAnswer } from '../page/src/view.ts';
import type { Input, View } from '../page/src/view.ts';
import { allOk, history, launch, simulate, worst } from './fixtures/made-up.ts';
import { mainHtml } from '../page/src/html.ts';

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

/** Every problem "Past problems" lists, newest first: the days', then the earlier ones. */
function probs(view: View): { kind: string; what: string; when: string }[] {
  return [...view.problems.days, ...view.problems.older].flatMap((day) => day.problems);
}

const ZONE = 'America/New_York';
/** Tue Nov 10 2026, 15:00 UTC (10:00 AM EST). */
const NOW = Date.UTC(2026, 10, 10, 15, 0, 0) / 1000;
const OK: Record<Part, State> = {
  site: 'ok',
  closings: 'ok',
  chances: 'ok',
  accounts: 'ok',
};

function summaryWith(
  states: Partial<Record<Part, State>>,
  incidents: SummaryIncident[] = [],
  since = 3,
): Summary {
  const base = simulate(NOW - since * DAY, NOW, () => OK);
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
    lead: 'Checking…',
    said: 'Checking…',
    more: null,
    stuck: {
      lead: 'This page did not finish loading.',
      more: 'Reload it to try again.',
    },
  });
  assert.deepEqual(
    view.parts.map((row) => [row.name, row.word, row.shape, row.updated]),
    [
      ['Website', 'Checking', 'wait', ''],
      ['Live school closings', 'Checking', 'wait', ''],
      ['Snow-day chances', 'Checking', 'wait', ''],
      ['Accounts', 'Checking', 'wait', ''],
    ],
  );
  assert.deepEqual(
    view.parts.map((row) => row.file),
    [false, true, true, false],
  );
  assert.deepEqual(
    view.history.map((block) => [block.mid, block.note, block.bars.length]),
    [
      ['', null, 90],
      ['', null, 90],
      ['', null, 90],
      ['', null, 90],
    ],
  );
  assert.deepEqual(
    view.parts.map((row) => row.updated),
    ['', '', '', ''],
  );
  assert.equal(
    view.history.every((block) =>
      block.bars.every((bar) => bar.cls === 'wait' && bar.label === null),
    ),
    true,
  );
  assert.deepEqual(view.problems, {
    days: [],
    empty: null,
    older: [],
    button: null,
    expanded: false,
    cut: null,
  });
});

test('before the first check, and when the status cannot be loaded', () => {
  const first = data(null);
  assert.deepEqual(first.banner, {
    shape: 'wait',
    lead: 'The first check is on its way.',
    said: 'The first check is on its way.',
    more: 'This page fills in within 5 minutes.',
    stuck: null,
  });
  assert.deepEqual(
    first.parts.map((row) => row.word),
    ['Checking', 'Checking', 'Checking', 'Checking'],
  );
  assert.deepEqual(
    first.history.map((block) => block.mid),
    Array.from({ length: 4 }, () => 'No checks yet'),
  );
  assert.deepEqual(
    first.parts.map((row) => row.updated),
    ['', 'Update time not known.', 'Update time not known.', ''],
  );
  // "Past problems" is never left blank: blank would read as "there were none".
  assert.equal(first.problems.empty, 'No checks yet.');
  const unreachable = viewOf({ kind: 'unreachable' });
  assert.deepEqual(unreachable.banner, {
    shape: 'unknown',
    lead: 'We cannot load the status.',
    said: 'We cannot load the status.',
    // One thing to do, said once: the history's line says to reload the page.
    more: null,
    stuck: null,
  });
  assert.deepEqual(
    unreachable.parts.map((row) => row.word),
    Array.from({ length: 4 }, () => 'Could not check'),
  );
  assert.deepEqual(
    unreachable.history.map((block) => block.mid),
    Array.from({ length: 4 }, () => 'Not loaded'),
  );
  assert.equal(
    unreachable.problems.empty,
    'The history could not be loaded. Reload the page to try again.',
  );
  // Not loaded is not drawn as the days before the checks began: no bar, an empty outline.
  for (const block of unreachable.history) {
    assert.deepEqual(new Set(block.bars.map((bar) => bar.cls)), new Set(['unloaded']));
  }
  const html = mainHtml(unreachable);
  assert.equal(html.includes('b-before'), false);
  assert.equal(
    html.match(/<div class="bars off" data-part="\w+" aria-hidden="true"><\/div>/g)?.length,
    4,
  );
  for (const block of first.history) {
    assert.deepEqual(new Set(block.bars.map((bar) => bar.cls)), new Set(['wait']));
  }
  // No bar has a name in either, so nothing invites a tap.
  for (const view of [first, unreachable]) {
    assert.deepEqual(
      view.history.map((block) => block.note),
      Array.from({ length: 4 }, () => null),
    );
    assert.deepEqual(view.problems.days, []);
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
    lead: 'Everything is working.',
    said: 'Everything is working.',
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  assert.deepEqual(data(summaryWith({ accounts: 'unknown' })).banner, {
    shape: 'unknown',
    lead: 'We could not check everything.',
    said: 'We could not check everything.',
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  // The headline is short; the parts are named in the card, and to a screen reader.
  const lateOne = data(summaryWith({ chances: 'late', accounts: 'unknown' })).banner;
  assert.deepEqual(
    [lateOne.shape, lateOne.lead, lateOne.said],
    ['late', 'Something is slow or late.', 'Slow or late right now: Snow-day chances.'],
  );
  assert.equal(
    data(summaryWith({ site: 'late', chances: 'late' })).banner.said,
    'Slow or late right now: Website and Snow-day chances.',
  );
  const both = data(
    summaryWith({
      site: 'down',
      closings: 'down',
      chances: 'down',
      accounts: 'late',
    }),
  );
  assert.deepEqual(both.banner, {
    shape: 'down',
    lead: 'Something is not working.',
    said:
      'Not working right now: Website, Live school closings and Snow-day chances. ' +
      'Slow or late right now: Accounts.',
    more: 'Last checked 2 minutes ago.',
    stuck: null,
  });
  assert.equal(
    data(summaryWith({ closings: 'down' })).banner.said,
    'Not working right now: Live school closings.',
  );
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
  const view = data(summaryWith({ chances: 'late' }), {
    kept: true,
    clock: NOW + 14 * 60,
  });
  assert.deepEqual(view.banner, {
    shape: 'late',
    lead: 'Something is slow or late.',
    said: 'Slow or late right now: Snow-day chances.',
    more: 'Could not refresh. Checked 14 minutes ago.',
    stuck: null,
  });
});

test('a file part says when it was updated, counted from its own stamp', () => {
  const view = data(summaryWith({ chances: 'down' }));
  assert.deepEqual(
    view.parts.map((row) => row.updated),
    ['', 'Updated 6 minutes ago.', 'Updated 6 minutes ago.', ''],
  );
  const none = summaryWith({});
  none.parts.chances = { s: 'unknown' };
  assert.deepEqual(
    data(none).parts.map((row) => row.updated),
    ['', 'Updated 6 minutes ago.', 'Update time not known.', ''],
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
  const unknown = data(summaryWith({ chances: 'unknown' }, [open]), {
    clock: NOW + 600,
  });
  assert.deepEqual(probs(unknown)[0], {
    kind: 'late',
    what: 'Snow-day chances: slow or late since Nov 10, 9:00 AM EST.',
    when: '50 minutes so far.',
  });
  // Seen late just now: the length runs to the page's clock.
  const late = data(summaryWith({ chances: 'late' }, [{ ...open, l: NOW }]), {
    clock: NOW + 600,
  });
  assert.equal(probs(late)[0]!.when, '1 hour 10 minutes so far.');
});

test('stale: after 900 s with no newer summary nothing is said to work', () => {
  const open: SummaryIncident = {
    p: 'chances',
    k: 'late',
    s: NOW - 3600,
    e: null,
    g: 0,
    l: NOW,
  };
  const summary = summaryWith({ chances: 'late' }, [open]);
  const fresh = data(summary, { clock: NOW + 900 });
  assert.equal(fresh.banner.shape, 'late');
  assert.deepEqual(probs(fresh)[0], {
    kind: 'late',
    what: 'Snow-day chances: slow or late since Nov 10, 9:00 AM EST.',
    when: '1 hour 15 minutes so far.',
  });
  for (const kept of [false, true]) {
    const stale = data(summary, { clock: NOW + 901, kept });
    assert.deepEqual(stale.banner, {
      shape: 'unknown',
      lead: 'We have no recent checks.',
      said: 'We have no recent checks.',
      more: 'The last check was 15 minutes ago.',
      stuck: null,
    });
    assert.deepEqual(
      stale.parts.map((row) => [row.word, row.updated]),
      [
        ['Could not check', ''],
        ['Could not check', 'Update time not known.'],
        ['Could not check', 'Update time not known.'],
        ['Could not check', ''],
      ],
    );
    // The open problem is drawn as one whose readings stopped, a tick after its last.
    assert.deepEqual(probs(stale)[0], {
      kind: 'late',
      what: 'Snow-day chances: slow or late for at least 1 hour 5 minutes.',
      when: 'From Nov 10, 9:00 AM EST. Our checks stopped while it was going on.',
    });
    // History stays, and today's bar says the time since the last check.
    assert.equal(stale.history[0]!.mid, '100% of checks working');
    assert.equal(stale.parts[1]!.updated, 'Update time not known.');
    assert.equal(
      stale.history[0]!.bars[89]!.label,
      'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 15 minutes.',
    );
  }
  assert.equal(
    fresh.history[0]!.bars[89]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working so far.',
  );
});

test('the day checks began is never said to be working all day', () => {
  const at = (iso: string): number => Date.parse(iso) / 1000;
  const first = at('2026-11-10T20:40:00Z');
  const last = (view: View, n: number): (string | null)[] =>
    view.history[0]!.bars.slice(-n).map((bar) => bar.label);
  // Clean from the first check on, read two days later.
  const clean = simulate(first, at('2026-11-12T09:00:00Z'), () => OK);
  assert.deepEqual(last(data(clean, { clock: clean.now + 130 }), 4), [
    'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: before checks began.',
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working since checks began.',
    'Nov 10, 7:00 PM to Nov 11, 7:00 PM EST: working all day.',
    'Nov 11, 7:00 PM to Nov 12, 7:00 PM EST: working so far.',
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
    'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: before checks began.',
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working since checks began.',
  ]);
  // A later gap on that day: its time with no check is counted from the day's start
  // (20 h 40 min before the first check, and the 30 minutes missed).
  const gap = simulate(first, at('2026-11-11T09:00:00Z'), (t) =>
    t >= at('2026-11-10T22:00:00Z') && t < at('2026-11-10T22:30:00Z') ? null : OK,
  );
  assert.deepEqual(last(data(gap, { clock: gap.now + 130 }), 2), [
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 21 hours 10 minutes.',
    'Nov 10, 7:00 PM to Nov 11, 7:00 PM EST: working so far.',
  ]);
  // Trouble on that day, with every check since the first kept.
  const bad = simulate(first, at('2026-11-11T09:00:00Z'), (t) =>
    t >= at('2026-11-10T21:00:00Z') && t < at('2026-11-10T22:00:00Z')
      ? { ...OK, site: 'down' }
      : OK,
  );
  assert.equal(
    data(bad, { clock: bad.now + 130 }).history[0]!.bars[88]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: not working for 1 hour, not checked for 20 hours 40 minutes.',
  );
  // Checks that began on a day's first tick did check all of it.
  const whole = simulate(at('2026-11-10T00:00:00Z'), at('2026-11-11T09:00:00Z'), () => OK);
  assert.equal(
    data(whole, { clock: whole.now + 130 }).history[0]!.bars[88]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working all day.',
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
    ['ok', 'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: working all day.'],
    [
      'ok',
      'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 8 hours 55 minutes.',
    ],
    ['none', 'Nov 10, 7:00 PM to Nov 11, 7:00 PM EST: not checked.'],
  ]);
  // Three days old: the bars moved up three days, so the last one is the clock's day.
  const three = data(summary, { clock: NOW + 3 * DAY + 2 * 3600 });
  assert.equal(three.banner.more, 'The last check was 3 days ago.');
  assert.deepEqual(tail(three, 5), [
    ['ok', 'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: working all day.'],
    [
      'ok',
      'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 8 hours 55 minutes.',
    ],
    ['none', 'Nov 10, 7:00 PM to Nov 11, 7:00 PM EST: not checked.'],
    ['none', 'Nov 11, 7:00 PM to Nov 12, 7:00 PM EST: not checked.'],
    ['none', 'Nov 12, 7:00 PM to Nov 13, 7:00 PM EST: not checked.'],
  ]);
  for (const view of [one, three]) {
    assert.equal(view.history[0]!.bars.length, 90);
    for (const block of view.history)
      for (const bar of block.bars) assert.equal(/today/i.test(bar.label ?? ''), false);
    // The share is of the checks that were made.
    assert.equal(view.history[0]!.mid, '100% of checks working');
  }
  // A picked bar is counted on the bars as drawn.
  assert.equal(
    data(summary, { clock: NOW + 3 * DAY, picked: { part: 'site', day: 86 } }).history[0]!.note,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 8 hours 55 minutes.',
  );
  // Checks that stopped early in a day: under half of it was checked, so it is not drawn working.
  const early = simulate(NOW - 3 * DAY, NOW - 9 * 3600, () => OK);
  assert.deepEqual(tail(data(early, { clock: NOW + DAY }), 2), [
    [
      'none',
      'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 17 hours 55 minutes.',
    ],
    ['none', 'Nov 10, 7:00 PM to Nov 11, 7:00 PM EST: not checked.'],
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
      ['ok', 'Nov 7, 7:00 PM to Nov 8, 7:00 PM EST: working all day.'],
      ['ok', 'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: working all day.'],
      ['yet', 'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: not checked yet.'],
    ],
  );
  // The day before, with its last tick not in yet, is not said to be whole.
  const short = simulate(midnight - 2 * DAY, midnight - 2 * TICK, () => OK);
  assert.equal(
    data(short, { clock: midnight + 120 }).history[0]!.bars[88]!.label,
    'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: working when checked; not checked for 5 minutes.',
  );
  // With the first tick of the day in, it is today again.
  const next = simulate(midnight - 2 * DAY, midnight, () => OK);
  assert.equal(
    data(next, { clock: midnight + 120 }).history[0]!.bars[89]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working so far.',
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
  assert.deepEqual(readAnswer(200, { served: 5, summary: null }), {
    served: 5,
    summary: null,
  });
  assert.deepEqual(readAnswer(200, { served: 5, summary }), {
    served: 5,
    summary,
  });
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
      ['before', 'Nov 3, 7:00 PM to Nov 4, 7:00 PM EST: before checks began.'],
      // Checks began at 06:00 UTC that day: every check since then was kept.
      ['ok', 'Nov 4, 7:00 PM to Nov 5, 7:00 PM EST: working since checks began.'],
      [
        'ok',
        'Nov 5, 7:00 PM to Nov 6, 7:00 PM EST: working when checked; not checked for 6 hours.',
      ],
      ['none', 'Nov 6, 7:00 PM to Nov 7, 7:00 PM EST: not checked.'],
      [
        'down',
        'Nov 7, 7:00 PM to Nov 8, 7:00 PM EST: not working for 1 hour, slow or late for 2 hours, not checked for 2 hours.',
      ],
      // Under half the day's checks: drawn as not checked, never as working.
      [
        'none',
        'Nov 8, 7:00 PM to Nov 9, 7:00 PM EST: working when checked; not checked for 20 hours.',
      ],
      ['ok', 'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working so far.'],
    ],
  );
  assert.equal(site.note, 'Nov 6, 7:00 PM to Nov 7, 7:00 PM EST: not checked.');
  assert.deepEqual(site.bars.map((bar) => bar.picked).indexOf(true), 86);
  // A block with no bar picked shows no tip.
  assert.equal(view.history[1]!.note, null);
  assert.equal(site.mid, '96.1% of checks working');
  // 889 of the 925 checks that gave a reading.
  const late = simulate(NOW - DAY, NOW, (t) =>
    t === NOW - 600 ? { ...OK, accounts: 'late' } : OK,
  );
  assert.equal(
    data(late).history[3]!.bars[89]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: slow or late for 5 minutes.',
  );
  assert.equal(data(late).history[3]!.bars[89]!.cls, 'late');
});

test('problems: closed, closed by a gap, open, and across a change of clocks', () => {
  const at = (iso: string): number => Date.parse(iso) / 1000;
  const incidents: SummaryIncident[] = [
    {
      p: 'chances',
      k: 'late',
      s: at('2026-11-10T13:55:00Z'),
      e: null,
      g: 0,
      l: NOW,
    },
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
    {
      p: 'site',
      k: 'late',
      s: at('2026-11-01T04:30:00Z'),
      e: at('2026-11-01T07:15:00Z'),
      g: 0,
    },
    // Across midnight: told in full on the day it began, and as going on into the next.
    {
      p: 'accounts',
      k: 'down',
      s: at('2026-10-20T03:50:00Z'),
      e: at('2026-10-20T04:10:00Z'),
      g: 0,
    },
  ];
  const summary = summaryWith({ chances: 'late' }, incidents, 40);
  const all = data(summary, { expanded: true, clock: NOW + 300 });
  // By the days each covered in the reader's zone, newest first; an open one is today's.
  assert.deepEqual(probs(all), [
    {
      kind: 'late',
      what: 'Snow-day chances: slow or late since Nov 10, 8:55 AM EST.',
      when: '1 hour 10 minutes so far.',
    },
    {
      kind: 'down',
      what: 'Live school closings: not working for 25 minutes.',
      when: 'Nov 7, 6:10 AM to 6:35 AM EST',
    },
    {
      kind: 'late',
      what: 'Website: slow or late for 2 hours 45 minutes.',
      when: 'Nov 1, 12:30 AM EDT to 2:15 AM EST',
    },
    {
      kind: 'down',
      what: 'Live school closings: not working for at least 10 minutes.',
      when: 'From Oct 30, 9:50 PM EDT. Our checks stopped while it was going on.',
    },
    {
      kind: 'down',
      what: 'Accounts: still not working from the day before.',
      when: 'Until 12:10 AM EDT.',
    },
    // It ended on another day: the end names its date.
    {
      kind: 'down',
      what: 'Accounts: not working for 20 minutes.',
      when: 'Oct 19, 11:50 PM to Oct 20, 12:10 AM EDT',
    },
  ]);
  assert.deepEqual(
    all.problems.days
      .filter((day) => day.problems.length > 0)
      .map((day) => [day.date, day.problems.length]),
    [
      ['Tue, Nov 10', 1],
      ['Sat, Nov 7', 1],
      ['Sun, Nov 1', 1],
      ['Fri, Oct 30', 1],
    ],
  );
  assert.deepEqual(
    all.problems.older.map((day) => day.date),
    ['Tue, Oct 20', 'Mon, Oct 19'],
  );
  assert.equal(all.problems.button, 'Hide earlier problems');
  assert.equal(all.problems.expanded, true);
  const some = data(summary);
  // Only the problem days of the fifteen listed: no date of a quiet day.
  assert.deepEqual(
    some.problems.days.map((day) => day.date),
    ['Tue, Nov 10', 'Sat, Nov 7', 'Sun, Nov 1', 'Fri, Oct 30'],
  );
  // The problem that began before the days listed is the one behind the button. It ran past
  // midnight, so the button shows two lines, one on each of its days, and says 2.
  assert.equal(some.problems.button, 'Show 2 earlier problems');
  // Another reader's zone gives the same instants in their own clock, on their own days.
  const utc = data(summary, { zone: 'UTC' });
  assert.equal(probs(utc)[1]!.when, 'Nov 7, 11:10 AM to 11:35 AM UTC');
  assert.deepEqual(
    utc.problems.days.filter((day) => day.problems.length > 0).map((day) => day.date),
    ['Tue, Nov 10', 'Sat, Nov 7', 'Sun, Nov 1', 'Sat, Oct 31'],
  );
});

test('past problems: only the problem days since checks began, and nothing of a quiet day', () => {
  const one = (i: number): SummaryIncident => ({
    p: 'site',
    k: 'down',
    s: NOW - (i + 1) * DAY,
    e: NOW - (i + 1) * DAY + 300,
    g: 0,
  });
  // Checks began Nov 7 and found no problem: no day is listed, and nothing is drawn.
  const none = data(summaryWith({}));
  assert.deepEqual(none.problems.days, []);

  assert.deepEqual(
    [none.problems.older, none.problems.button, none.problems.empty, none.problems.cut],
    [[], null, null, null],
  );
  assert.equal(mainHtml(none).includes('Past problems'), false);
  // Launch day ten hours in, all working: no day, never a column of days before the checks.
  const launchDay = data(simulate(NOW - 10 * 3600, NOW, () => OK));
  assert.deepEqual(launchDay.problems.days, []);

  // Ninety days of checks, all working: no day, and no "Past problems".
  const full = data(allOk(NOW));
  assert.deepEqual([full.problems.days, full.problems.older, full.problems.button], [[], [], null]);

  assert.equal(mainHtml(full).includes('Past problems'), false);
  const long = (incidents: SummaryIncident[]): Summary => summaryWith({}, incidents, 40);
  const two = data(long([one(0), one(1)]));
  // The two problem days, and no line of the quiet days around them.
  assert.deepEqual(
    two.problems.days.map((day) => [day.date, day.problems.length, day.none]),
    [
      ['Mon, Nov 9', 1, null],
      ['Sun, Nov 8', 1, null],
    ],
  );
  const html = mainHtml(two);
  assert.equal(html.match(/<li class="day">/g)?.length, 2);
  assert.doesNotMatch(html, /No problems/);
  const many = data(long([one(0), one(13), one(14), one(15)]));
  assert.deepEqual(
    [probs(many).length, many.problems.older.length, many.problems.button],
    [4, 2, 'Show 2 earlier problems'],
  );
  // A part that could not be checked just now: today is listed with that note, the quiet
  // days before are not.
  const unknown = data(summaryWith({ accounts: 'unknown' }));
  assert.deepEqual(
    unknown.problems.days.map((day) => [day.date, day.none]),
    [['Tue, Nov 10', 'Not every part could be checked.']],
  );
});

test('"Past problems" draws only problem days and gap days, and nothing when there are none', () => {
  const down = (back: number): SummaryIncident => ({
    p: 'site',
    k: 'down',
    s: NOW - back * DAY,
    e: NOW - back * DAY + 600,
    g: 0,
  });
  // No problem day: no section, no date, no sentence of no problems.
  for (const html of [
    mainHtml(data(summaryWith({}, [], 40))),
    mainHtml(data(allOk(NOW), { expanded: true })),
  ]) {
    assert.doesNotMatch(html, /h-problems|class="day"|<time>|No problems/);
  }
  // One problem 20 days back, behind the button: the section is its heading and the button.
  const folded = data(summaryWith({}, [down(20)], 40));
  assert.deepEqual([folded.problems.days, folded.problems.older.length], [[], 1]);
  const html = mainHtml(folded);
  assert.match(html, /id="h-problems"/);
  assert.doesNotMatch(html, /class="day"/);
  assert.match(html, /<button[^>]*>Show 1\searlier problem<\/button>/);
  const open = mainHtml(data(summaryWith({}, [down(20)], 40), { expanded: true }));
  assert.equal(open.match(/class="day"/g)?.length, 1);
  // A day the checker missed in full, with no problem: its date and note, never left out.
  const gappy = summaryWith({}, [], 40);
  gappy.days.site[85] = [0, 0, 0];
  const gap = data(gappy);
  assert.deepEqual(
    gap.problems.days.map((day) => [day.date, day.problems.length, day.none]),
    [
      ['Fri, Nov 6', 0, 'This day was not checked in full.'],
      ['Thu, Nov 5', 0, 'This day was not checked in full.'],
    ],
  );
  // Checks late on a day with a problem: that day says it was not checked in full too.
  const late = data(history(NOW), { clock: NOW + 2000 });
  assert.equal(late.problems.days[0]!.problems.length > 0, true);
  assert.equal(late.problems.days[0]!.note, 'This day was not checked in full.');
  assert.equal(data(history(NOW), { clock: NOW + 130 }).problems.days[0]!.note, null);
  assert.match(
    mainHtml(gap),
    /<li class="day"><h3><time>Fri, Nov\s6<\/time><\/h3><p class="none">This day was not checked in\sfull\.<\/p><\/li>/,
  );
});

const at = (iso: string): number => Date.parse(iso) / 1000;
/** What "Past problems" says of each day, newest first: its line, or its problems. */
function told(view: View): string[] {
  return view.problems.days.map(
    (day) =>
      `${day.date}: ${day.none ?? day.problems.map((p) => `${p.what} ${p.when}`).join(' | ')}` +
      (day.note === null ? '' : ` (${day.note})`),
  );
}

test('a problem is listed on every day it covered, so no such day says "No problems."', () => {
  // Down from Nov 5 13Z to Nov 8 15Z, then working: the bars are red on all four UTC days.
  const closed = simulate(NOW - 20 * DAY, NOW, (t) =>
    t >= at('2026-11-05T13:00:00Z') && t < at('2026-11-08T15:00:00Z')
      ? { ...OK, site: 'down' }
      : OK,
  );
  const view = data(closed);
  assert.deepEqual(
    view.history[0]!.bars.slice(83, 89).map((bar) => bar.cls),
    ['ok', 'down', 'down', 'down', 'down', 'ok'],
  );
  assert.deepEqual(told(view).slice(0, 7), [
    'Sun, Nov 8: Website: still not working from the day before. Until 10:00 AM EST.',
    'Sat, Nov 7: Website: still not working from the day before. All day.',
    'Fri, Nov 6: Website: still not working from the day before. All day.',
    'Thu, Nov 5: Website: not working for 3 days 2 hours. Nov 5, 8:00 AM to Nov 8, 10:00 AM EST',
  ]);
  // Down since Nov 8 15Z and still: today in full, the day it began from its time, and between.
  const open = simulate(NOW - 20 * DAY, NOW, (t) =>
    t >= at('2026-11-08T15:00:00Z') ? { ...OK, site: 'down' } : OK,
  );
  const now = data(open);
  assert.equal(now.banner.lead, 'Something is not working.');
  assert.deepEqual(told(now).slice(0, 4), [
    'Tue, Nov 10: Website: not working since Nov 8, 10:00 AM EST. 2 days so far.',
    'Mon, Nov 9: Website: still not working from the day before. All day.',
    'Sun, Nov 8: Website: not working from 10:00 AM EST. Still going on.',
  ]);
  // A day whose bar is red is never bare.
  for (const summary of [closed, open]) {
    const shown = data(summary);
    const red = new Set(
      shown.history[0]!.bars.flatMap((bar) =>
        bar.cls === 'down' ? [bar.label!.split(':')[0]] : [],
      ),
    );
    for (const day of shown.problems.days)
      if (red.has(day.date)) assert.equal(day.none, null, day.date);
  }
});

test('a day with too few checks is never said to have no problems', () => {
  // No readings at all from Nov 3 00Z to Nov 7 00Z: the checker stopped.
  const gap = simulate(NOW - 20 * DAY, NOW, (t) =>
    t >= at('2026-11-03T00:00:00Z') && t < at('2026-11-07T00:00:00Z') ? null : OK,
  );
  const stopped = data(gap);
  assert.deepEqual(
    stopped.history[0]!.bars.slice(81, 87).map((bar) => bar.cls),
    ['ok', 'none', 'none', 'none', 'none', 'ok'],
  );
  assert.deepEqual(told(stopped), [
    // Its evening is the UTC day the checks stopped in.
    'Fri, Nov 6: This day was not checked in full.',
    'Thu, Nov 5: Not checked.',
    'Wed, Nov 4: Not checked.',
    'Tue, Nov 3: Not checked.',
    'Mon, Nov 2: This day was not checked in full.',
  ]);
  // Every reading of Nov 4 and 5 was Could not check: the checker's own failure.
  const unknown: Record<Part, State> = {
    site: 'unknown',
    closings: 'unknown',
    chances: 'unknown',
    accounts: 'unknown',
  };
  const blind = simulate(NOW - 20 * DAY, NOW, (t) =>
    t >= at('2026-11-04T00:00:00Z') && t < at('2026-11-06T00:00:00Z') ? unknown : OK,
  );
  assert.deepEqual(told(data(blind)), [
    'Thu, Nov 5: This day was not checked in full.',
    'Wed, Nov 4: Not checked.',
    'Tue, Nov 3: This day was not checked in full.',
  ]);
});

test('a day is said to have no problems only when its checks had answers, counted from the bars', () => {
  // Case A: every part answered only half of Nov 9 UTC and 228 of 288 checks of Nov 10 UTC.
  // Both bars are drawn working, yet New York's Nov 8 and Nov 9 each had hours with no answer.
  // The 60 of Nov 10 UTC were its first 5 hours, all on New York's Nov 9: its Nov 10, a day
  // that straddles two UTC days, was checked in full and is not listed.
  const clock = at('2026-11-12T17:00:00Z');
  const halves = simulate(clock - 20 * DAY, clock, (t) => {
    if (t >= at('2026-11-09T00:00:00Z') && t < at('2026-11-09T12:00:00Z')) return null;
    if (t >= at('2026-11-10T00:00:00Z') && t < at('2026-11-10T05:00:00Z')) return null;
    return OK;
  });
  assert.deepEqual(halves.days.site.slice(-4, -2), [
    [144, 0, 0],
    [228, 0, 0],
  ]);
  const a = data(halves, { clock: clock + 130 });
  assert.deepEqual(
    a.history[0]!.bars.slice(86, 88).map((bar) => bar.cls),
    ['ok', 'ok'],
  );
  assert.deepEqual(told(a), [
    'Mon, Nov 9: This day was not checked in full.',
    // Its evening is the first 12 hours of Nov 9 UTC.
    'Sun, Nov 8: This day was not checked in full.',
  ]);

  // Case B: the chances had no answer for a third of every day: no day says "No problems."
  const third = simulate(clock - 20 * DAY, clock, (t) =>
    t % DAY < 8 * 3600 ? { ...OK, chances: 'unknown' } : OK,
  );
  const b = data(third, { clock: clock + 130 });
  assert.equal(b.history[2]!.bars[85]!.cls, 'ok');
  assert.equal(
    b.problems.days.some((day) => day.none === 'No problems.'),
    false,
  );

  // A 17-hour gap in New York's Sat, Nov 7 (12:05Z to 05:00Z the next day) leaves both of its
  // bars drawn working; the day is not said to have no problems, and its tip names the gap.
  const gap = simulate(at('2026-10-20T00:00:00Z'), at('2026-11-12T02:05:00Z'), (t) =>
    t > at('2026-11-07T12:00:00Z') && t < at('2026-11-08T05:00:00Z') ? null : OK,
  );
  const c = data(gap, { clock: at('2026-11-12T02:07:10Z') });
  assert.deepEqual(
    c.history[0]!.bars.slice(84, 86).map((bar) => [bar.cls, bar.label]),
    [
      [
        'ok',
        'Nov 6, 7:00 PM to Nov 7, 7:00 PM EST: working when checked; not checked for 11 hours 55 minutes.',
      ],
      [
        'ok',
        'Nov 7, 7:00 PM to Nov 8, 7:00 PM EST: working when checked; not checked for 5 hours.',
      ],
    ],
  );
  assert.equal(
    told(c).find((line) => line.startsWith('Sat, Nov 7')),
    'Sat, Nov 7: This day was not checked in full.',
  );

  // A missed check a day, the cron's own way, is inside the allowance: those days have none.
  const routine = simulate(clock - 20 * DAY, clock, (t) => (t % DAY === 7 * 3600 ? null : OK));
  assert.deepEqual(told(data(routine, { clock: clock + 130 })), []);
  assert.equal(page.UNANSWERED_ALLOWED, 2);
});

test('the day after the checks stopped on a problem says what they last found', () => {
  // The closings are down from 03:00Z Nov 2 (10 PM EST Nov 1); the checks stop at 03:15Z and
  // come back at 09:15Z, so New York's Nov 2 begins with 4 hours of no answer.
  const clock = at('2026-11-10T15:00:00Z');
  const run = (back: string): Summary =>
    simulate(clock - 20 * DAY, clock, (t) => {
      if (t >= at('2026-11-02T03:15:00Z') && t < at(back)) return null;
      if (t >= at('2026-11-02T03:00:00Z') && t < at('2026-11-02T03:15:00Z')) {
        return { ...OK, closings: 'down' };
      }
      return OK;
    });
  const long = told(data(run('2026-11-02T09:15:00Z')));
  assert.deepEqual(
    long.filter((line) => line.startsWith('Mon, Nov 2') || line.startsWith('Sun, Nov 1')),
    [
      'Mon, Nov 2: Live school closings: not working when our checks stopped on Nov 1, ' +
        '10:15 PM EST. This day was not checked in full.',
      // Its last 21 checks, 03:15Z to 05:00Z, had no answer: it says so after its problem.
      'Sun, Nov 1: Live school closings: not working for at least 15 minutes. From Nov 1, ' +
        '10:00 PM EST. Our checks stopped while it was going on. ' +
        '(This day was not checked in full.)',
    ],
  );
  // Back at 05:45Z, 45 minutes past New York's midnight: the day says what the checks last
  // found, and that line already says it was not checked in full.
  const short = told(data(run('2026-11-02T05:45:00Z')));
  assert.equal(
    short.find((line) => line.startsWith('Mon, Nov 2')),
    'Mon, Nov 2: Live school closings: not working when our checks stopped on Nov 1, ' +
      '10:15 PM EST. This day was not checked in full.',
  );
  // Back at 03:25Z, before midnight: 2 checks with no answer, inside the allowance (and too
  // short to end the problem as a stop), so neither day says it was not checked in full.
  const back = told(data(run('2026-11-02T03:25:00Z')));
  assert.deepEqual(
    back.filter((line) => line.startsWith('Mon, Nov 2') || line.startsWith('Sun, Nov 1')),
    [
      'Sun, Nov 1: Live school closings: not working for 25 minutes. ' +
        'Nov 1, 10:00 PM to 10:25 PM EST',
    ],
  );
  // Back at 04:00Z: 9 checks with no answer, all on Sun, Nov 1 in New York. Nov 2 UTC is the
  // end of Sun, Nov 1 and most of Mon, Nov 2; the summary's runs say when the 9 were, so only
  // Sun, Nov 1 says it was not checked in full, and Mon, Nov 2, checked in full, is not listed.
  const nine = told(data(run('2026-11-02T04:00:00Z')));
  assert.deepEqual(
    nine.filter((line) => line.startsWith('Mon, Nov 2') || line.startsWith('Sun, Nov 1')),
    [
      'Sun, Nov 1: Live school closings: not working for at least 15 minutes. From Nov 1, ' +
        '10:00 PM EST. Our checks stopped while it was going on. ' +
        '(This day was not checked in full.)',
    ],
  );
});

test('a part with 3 checks of a day unanswered never lets that day be left out as quiet', () => {
  // The chances give no answer from 15:00Z Nov 5 (10:00 AM EST, Thu, Nov 5) for n checks.
  const clock = at('2026-11-10T15:00:00Z');
  const run = (n: number): string[] =>
    told(
      data(
        simulate(clock - 20 * DAY, clock, (t) => {
          const k = (t - at('2026-11-05T15:00:00Z')) / TICK;
          return k >= 0 && k < n ? { ...OK, chances: 'unknown' } : OK;
        }),
      ),
    ).filter((line) => line.startsWith('Thu, Nov 5') || line.startsWith('Wed, Nov 4'));
  // Two are inside the allowance: both days are quiet, and neither is listed.
  assert.deepEqual(run(2), []);
  // Three are not. Nov 5 UTC is also the last 5 hours of Wed, Nov 4 in New York, but the
  // three were all on Thu, Nov 5 there: Wed, Nov 4 was checked in full and is not listed.
  assert.deepEqual(run(3), ['Thu, Nov 5: This day was not checked in full.']);
  for (const n of [3, 4, 12, 30, 287]) {
    assert.equal(run(n)[0], 'Thu, Nov 5: This day was not checked in full.', `${n} unanswered`);
  }
});

test('a day with a problem says when it was not checked in full, and only once', () => {
  // The site down for 10 minutes at 15:00Z Nov 5 (10:00 AM EST); the checks away from 18:00Z
  // for `away` checks of the same day.
  const clock = at('2026-11-10T15:00:00Z');
  const run = (away: number): string[] =>
    told(
      data(
        simulate(clock - 20 * DAY, clock, (t) => {
          const k = (t - at('2026-11-05T18:00:00Z')) / TICK;
          if (k >= 0 && k < away) return null;
          if (t >= at('2026-11-05T15:00:00Z') && t < at('2026-11-05T15:10:00Z')) {
            return { ...OK, site: 'down' };
          }
          return OK;
        }),
      ),
    ).filter((line) => line.startsWith('Thu, Nov 5'));
  const down = 'Thu, Nov 5: Website: not working for 10 minutes. Nov 5, 10:00 AM to 10:10 AM EST';
  assert.deepEqual(run(0), [down]);
  assert.deepEqual(run(2), [down]);
  // A two-hour gap the same day: the problem, then the note.
  assert.deepEqual(run(24), [`${down} (This day was not checked in full.)`]);

  // A line that says the checks stopped already says it: the note is not said twice.
  const stop = told(
    data(
      simulate(clock - 20 * DAY, clock, (t) => {
        if (t >= at('2026-11-05T03:15:00Z') && t < at('2026-11-05T09:15:00Z')) return null;
        if (t >= at('2026-11-05T03:00:00Z') && t < at('2026-11-05T03:15:00Z')) {
          return { ...OK, closings: 'down' };
        }
        return OK;
      }),
    ),
  ).find((line) => line.startsWith('Thu, Nov 5'));
  assert.equal(stop?.endsWith('This day was not checked in full.'), true);
  assert.equal(stop?.match(/not checked in full/g)?.length, 1);
});

test("a part's run of short problems on one day is one line", () => {
  // The accounts slow for 5 minutes every half hour of Nov 5 UTC: 48 problems.
  const clock = at('2026-11-10T15:00:00Z');
  const flap = simulate(clock - 20 * DAY, clock, (t) =>
    t >= at('2026-11-05T05:00:00Z') && t < at('2026-11-06T05:00:00Z') && t % 1800 === 0
      ? { ...OK, accounts: 'late' }
      : OK,
  );
  const view = data(flap);
  assert.deepEqual(
    told(view).filter((line) => line.startsWith('Thu, Nov 5')),
    [
      'Thu, Nov 5: Accounts: slow or late 48 times, 4 hours in all. Nov 5, 12:00 AM to 11:35 PM EST',
    ],
  );
  // Two of them are two lines.
  const two = simulate(clock - 20 * DAY, clock, (t) =>
    t === at('2026-11-05T15:00:00Z') || t === at('2026-11-05T16:00:00Z')
      ? { ...OK, accounts: 'late' }
      : OK,
  );
  assert.equal(probs(data(two)).length, 2);
  assert.equal(page.RUN_TOLD_AS_ONE, 3);
});

test('a full summary never leaves out as quiet a day whose problems it left out', () => {
  // Accounts slow for five minutes every 20 from Nov 4 00Z for 43 hours: 130 problems, of
  // which the summary keeps the newest 100.
  const begin = at('2026-11-04T00:00:00Z');
  const flap = simulate(NOW - 20 * DAY, NOW, (t) => {
    const k = (t - begin) / TICK;
    return k >= 0 && k < 520 && k % 4 === 0 ? { ...OK, accounts: 'late' } : OK;
  });
  assert.equal(flap.incidents.length, INCIDENTS_MAX);
  const view = data(flap);
  const days = told(view);
  const on = (lines: string[], date: string): string | undefined =>
    lines.find((line) => line.startsWith(`${date}:`));
  assert.equal(
    on(days, 'Wed, Nov 4')!.endsWith('(Some problems from this day are not listed.)'),
    true,
  );
  assert.equal(on(days, 'Tue, Nov 3'), 'Tue, Nov 3: Some problems from this day are not listed.');
  // The quiet day before them is not listed.
  assert.equal(days.at(-1), 'Tue, Nov 3: Some problems from this day are not listed.');
  assert.equal(
    view.problems.cut,
    'This list holds the newest 100 problems. Older ones are not shown.',
  );
  // Three of the site's checks at 12:00Z Nov 4 with no answer too: both notes, as one, on
  // that day; the day before keeps its one note.
  const short = structuredClone(flap);
  const bar = short.days.site[83]!;
  short.days.site[83] = [bar[0] - 3, bar[1], bar[2]];
  short.miss!.runs.site.push([at('2026-11-04T12:00:00Z'), 3]);
  short.miss!.runs.site.sort((x, y) => x[0] - y[0]);
  const both = told(data(short));
  assert.equal(
    on(both, 'Wed, Nov 4')!.endsWith(
      '(Some problems from this day are not listed. This day was not checked in full.)',
    ),
    true,
  );
  assert.equal(on(both, 'Tue, Nov 3'), 'Tue, Nov 3: Some problems from this day are not listed.');
  // One fewer problem and nothing is cut.
  const fewer = structuredClone(flap);
  fewer.incidents = fewer.incidents.slice(0, INCIDENTS_MAX - 1);
  assert.equal(data(fewer).problems.cut, null);
});

test('a part no check could reach says so, and an old summary says nothing of the days since', () => {
  // Launch day: the chances' stamp is not on the host, so every check of them gave no answer.
  const first = data(launch(NOW));
  assert.equal(first.banner.lead, 'We could not check everything.');
  assert.deepEqual(
    first.history.map((block) => block.mid),
    [
      '100% of checks working',
      '100% of checks working',
      'Could not check',
      '100% of checks working',
    ],
  );
  // Launch day is the only day listed, and the list ends with when the checks began.
  assert.deepEqual(
    first.problems.days.map((day) => day.none),
    ['Not every part could be checked.'],
  );

  // "No checks yet" is said before the first check only.
  assert.equal(JSON.stringify(first).includes('No checks yet'), false);

  // A quiet summary a day old: no problem is known, and the time since the last check is a
  // gap, never a quiet day: the day since is not checked, the last one not checked in full.
  const quiet = summaryWith({});
  const day = data(quiet, { clock: NOW + DAY });
  assert.deepEqual(
    day.problems.days.map((one) => [one.date, one.none]),
    [
      ['Wed, Nov 11', 'Not checked.'],
      ['Tue, Nov 10', 'This day was not checked in full.'],
    ],
  );
  assert.deepEqual(data(allOk(NOW), { clock: NOW + DAY }).problems.days, day.problems.days);
  // Not yet stale, and only the refresh failed: the quiet day is still not listed.
  assert.deepEqual(data(quiet, { clock: NOW + 800, kept: true }).problems.days, []);

  // The list is of the 90 days the bars show. The made-up history has four problems: 20, 10
  // and 3 days back, and one open. Read 85 days late, the bars begin 4 days before its last
  // check, so the two older ones are gone and the open one ends where the checks stopped.
  const old = history(NOW);
  // The four, and the day after the checks stopped on the closings: what they last found.
  assert.equal(probs(data(old, { expanded: true })).length, 5);
  const late = data(old, { clock: NOW + 85 * DAY, expanded: true });
  assert.equal(
    late.history[0]!.bars[0]!.label,
    'Nov 5, 7:00 PM to Nov 6, 7:00 PM EST: working all day.',
  );
  assert.deepEqual(probs(late), [
    {
      kind: 'late',
      what: 'Snow-day chances: slow or late for at least 1 hour 10 minutes.',
      when: 'From Nov 10, 8:55 AM EST. Our checks stopped while it was going on.',
    },
    {
      kind: 'down',
      what: 'Live school closings: not working for 25 minutes.',
      when: 'Nov 7, 6:10 AM to 6:35 AM EST',
    },
  ]);
  // The days listed are after the last check: none of them is said to have no problems.
  assert.equal(
    late.problems.days.every((one) => one.none === 'Not checked.'),
    true,
  );
  assert.equal(late.problems.button, 'Hide earlier problems');

  // 100 days late: no day shown was checked. Each bar is a day of the clock's own 90, the
  // last one the clock's day; nothing is listed; and the lines say why, not "No checks yet".
  const gone = data(old, { clock: NOW + 100 * DAY, expanded: true });
  assert.equal(gone.banner.lead, 'We have no recent checks.');
  assert.deepEqual(
    gone.history.map((block) => block.mid),
    Array.from({ length: 4 }, () => 'No recent checks'),
  );
  // Every one of the days is a gap, never a quiet day: fifteen listed, the rest behind the
  // button, each "Not checked.".
  assert.deepEqual(
    [gone.problems.button, gone.problems.empty, gone.problems.days.length],
    ['Hide earlier problems', null, 15],
  );
  // The 90 UTC bars touch 91 of the reader's days.
  assert.equal(gone.problems.days.length + gone.problems.older.length, 91);
  assert.equal(
    [...gone.problems.days, ...gone.problems.older].every(
      (one) => one.problems.length === 0 && one.none === 'Not checked.',
    ),
    true,
  );
  assert.equal(data(old, { clock: NOW + 100 * DAY }).problems.button, 'Show 76 earlier problems');
  const bars = gone.history[0]!.bars;
  assert.deepEqual(
    [bars[0]!.label, bars[89]!.label],
    [
      'Nov 20, 7:00 PM to Nov 21, 7:00 PM EST: not checked.',
      'Feb 17, 7:00 PM to Feb 18, 7:00 PM EST: not checked.',
    ],
  );
  assert.equal(
    bars.every((bar) => bar.cls === 'none'),
    true,
  );
  // 89 days late: the summary's last day is still the first bar.
  const edge = data(old, { clock: NOW + 89 * DAY });
  assert.equal(
    edge.history[0]!.bars[0]!.label,
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: working when checked; not checked for 8 hours 55 minutes.',
  );
  assert.equal(edge.history[0]!.mid, '100% of checks working');
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
    'Nov 9, 7:00 PM to Nov 10, 7:00 PM EST: not checked.',
  );
  // A day before the checks began keeps its own kind.
  assert.equal(data(eve, { clock: midnight + 100 }).history[0]!.bars[86]!.cls, 'before');
});

test('the made-up history reads as the pictures show it', () => {
  const view = data(history(NOW), { clock: NOW + 130 });
  assert.deepEqual(
    [view.banner.lead, view.banner.said],
    ['Something is slow or late.', 'Slow or late right now: Snow-day chances.'],
  );
  assert.equal(view.history[0]!.bars.filter((bar) => bar.cls === 'before').length, 30);
  assert.equal(
    view.history[1]!.bars[79]!.label,
    'Oct 30, 8:00 PM to Oct 31, 8:00 PM EDT: not working for 15 minutes, not checked for 6 hours.',
  );
  assert.equal(view.history[3]!.mid, '100% of checks working');
  // The website's slow spell 20 days back is behind the button.
  assert.equal(view.problems.button, 'Show 1 earlier problem');
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
      ['Not working', ''],
      // Late for a day before it stopped: its file is older than the outage.
      ['Not working', 'Updated 3 days ago.'],
      ['Not working', 'Updated 2 days ago.'],
      ['Slow or late', ''],
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

test('a day checked in full that straddles two UTC days is never said to have a gap', () => {
  // The chances give no answer for 3 checks from 02:00Z Nov 6: 9:00 PM EST on Thu, Nov 5.
  // Fri, Nov 6 in New York (05:00Z Nov 6 to 05:00Z Nov 7) shares the bar of Nov 6 UTC with
  // them, yet had every check answered.
  const clock = at('2026-11-10T15:00:00Z');
  const summary = simulate(clock - 20 * DAY, clock, (t) => {
    const k = (t - at('2026-11-06T02:00:00Z')) / TICK;
    return k >= 0 && k < 3 ? { ...OK, chances: 'unknown' } : OK;
  });
  assert.deepEqual(summary.miss!.runs.chances, [[at('2026-11-06T02:00:00Z'), 3]]);
  const view = data(summary, { clock: clock + 130 });
  assert.deepEqual(told(view), ['Thu, Nov 5: This day was not checked in full.']);
  assert.doesNotMatch(mainHtml(view), /Fri, Nov\s6/);
  // A store written before the runs were kept says only what its bars prove: the 3 can be
  // on either day, so neither is said to have a gap.
  const older = structuredClone(summary);
  delete older.miss;
  assert.deepEqual(told(data(older, { clock: clock + 130 })), []);
  // Runs that make no sense are read as none.
  const broken = structuredClone(summary) as unknown as { miss: unknown };
  broken.miss = { since: 'x', runs: {} };
  assert.deepEqual(told(data(broken as unknown as Summary, { clock: clock + 130 })), []);
});

test('a store with no runs still says what its bars prove', () => {
  // No readings at all through Nov 4 UTC: whatever the runs, the bars prove most of New
  // York's Nov 3 evening and Nov 4 had no answer.
  const clock = at('2026-11-10T15:00:00Z');
  const summary = simulate(clock - 20 * DAY, clock, (t) =>
    t >= at('2026-11-04T00:00:00Z') && t < at('2026-11-05T00:00:00Z') ? null : OK,
  );
  const exact = told(data(summary, { clock: clock + 130 }));
  delete summary.miss;
  const proven = told(data(summary, { clock: clock + 130 }));
  assert.deepEqual(exact, [
    'Wed, Nov 4: This day was not checked in full.',
    'Tue, Nov 3: This day was not checked in full.',
  ]);
  assert.deepEqual(proven, exact);
});

test('the fold counts the lines it shows, never a problem already shown open today', () => {
  // A chances problem open since 13:55Z today and two older closings outages, 20 and 25 days
  // back: the button says 2, and shows 2 lines.
  const clock = NOW + 130;
  const outage = (back: number): SummaryIncident => ({
    p: 'closings',
    k: 'down',
    s: NOW - back * DAY,
    e: NOW - back * DAY + 600,
    g: 0,
  });
  const summary = summaryWith(
    { chances: 'late' },
    [
      { p: 'chances', k: 'late', s: at('2026-11-10T13:55:00Z'), e: null, g: 0, l: NOW },
      outage(20),
      outage(25),
    ],
    40,
  );
  const shut = data(summary, { clock });
  assert.equal(shut.problems.days[0]!.problems[0]!.what.startsWith('Snow-day chances'), true);
  assert.equal(shut.problems.button, 'Show 2 earlier problems');
  // The same count when the open one began before the days listed: its lines on those days
  // are counted, and its line under today is not.
  const long = summaryWith(
    { chances: 'late' },
    [{ p: 'chances', k: 'late', s: NOW - 17 * DAY, e: null, g: 0, l: NOW }, outage(20), outage(25)],
    40,
  );
  for (const one of [summary, long, history(NOW), launch(NOW), worst(NOW)]) {
    const folded = data(one, { clock });
    const open = data(one, { clock, expanded: true });
    const older = /<ol class="days older">(.*?)<\/ol><p class="more-row">/s.exec(mainHtml(open));
    const lines =
      (older?.[1]!.match(/<li class="prob">/g)?.length ?? 0) +
      (older?.[1]!.match(/<p class="none">/g)?.length ?? 0);
    const n = folded.problems.button === null ? 0 : Number(/\d+/.exec(folded.problems.button)![0]);
    assert.equal(n, lines);
  }
  // Its began line and two still lines (Oct 24 to 26), and the two outages.
  assert.equal(data(long, { clock }).problems.button, 'Show 5 earlier problems');
});

test('the history that could not load says one thing to do, once', () => {
  const html = mainHtml(page.viewOf({ kind: 'unreachable' }));
  assert.equal(html.match(/Reload/g)?.length, 1);
  assert.match(html, /The history could not be loaded\. Reload the page to try again\./);
  assert.doesNotMatch(html, /tries again|try again every/);
});

test('no line says when the checks began', () => {
  for (const one of [launch(NOW), history(NOW), allOk(NOW), worst(NOW)]) {
    for (const expanded of [false, true]) {
      assert.doesNotMatch(mainHtml(data(one, { expanded })), /Checks began on|checks began on/);
    }
  }
});

test('a day note is drawn as every other line: its tied runs in boxes', () => {
  const clock = at('2026-11-10T15:00:00Z');
  const summary = simulate(clock - 20 * DAY, clock, (t) => {
    const k = (t - at('2026-11-05T15:00:00Z')) / TICK;
    if (k >= 0 && k < 30) return null;
    return k === 40 ? { ...OK, site: 'down' } : OK;
  });
  const html = mainHtml(
    page.viewOf({
      kind: 'data',
      summary,
      clock: clock + 130,
      kept: false,
      expanded: false,
      picked: null,
      zone: ZONE,
    }),
  );
  assert.match(
    html,
    /<p class="none note">This day was not checked <span class="nb">in full\.<\/span><\/p>/,
  );
  // No line of the list keeps a bare no-break space: each tied run is a box, as in a tip.
  const lines = html.match(/<p class="(?:none|what|when)[^"]*">.*?<\/p>/g) ?? [];
  assert.equal(lines.length > 0, true);
  for (const line of lines) assert.equal(line.includes('\u00a0'), false, line);
});

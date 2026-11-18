import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { build } from '../page/build.mjs';
import { CANONICAL_URL, HOME_URL, copy } from '../page/src/copy.ts';
import { mainHtml, pageHtml } from '../page/src/html.ts';
import { viewOf } from '../page/src/view.ts';
import type { Input } from '../page/src/view.ts';
import { INCIDENTS_MAX } from '../shared/history.ts';
import { DAY } from '../shared/types.ts';
import type { Summary } from '../shared/types.ts';
import { allOk, history, launch, simulate, worst } from './fixtures/made-up.ts';
import { root } from './harness.ts';

/** The words as a reader sees them: a no-break space as a space, the word joiner gone. */
const plain = (text: string): string => text.replace(/[\u00a0\u202f]/g, ' ').replace(/\u2060/g, '');

/**
 * The places a line must never break, in a text of the page: after a number and before its
 * word ("5 minutes", "7 PM"), inside a date ("Nov 10"), between a time and its zone
 * ("PM EST"), after the hyphen of a name ("Snow-day"), between a count and its "ago"
 * ("2 minutes ago", "just now"), inside a length of two parts ("1 hour 10 minutes"), inside a
 * part's name ("Live school closings") and inside "at least".
 */
function breaks(text: string): string[] {
  return [
    ...text.matchAll(
      /\d [A-Za-z]+|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d+|[AP]M [A-Z]\w*|\w+-[A-Za-z]+|\b(?:minutes?|hours?|days?) (?:ago|\d+)|just now|at least|Live school|school closings|day chances/g,
    ),
  ].map((m) => m[0]);
}

let out: string;
const file = (name: string): string => readFileSync(join(out, name), 'utf8');

before(async () => {
  out = mkdtempSync(join(tmpdir(), 'snowlight-status-build-'));
  await build(out);
});
after(() => {
  rmSync(out, { recursive: true, force: true });
});

test('the built folder holds the page and nothing else', () => {
  assert.deepEqual(readdirSync(out).sort(), [
    '_headers',
    '_routes.json',
    'app.js',
    'favicon-16.png',
    'favicon-32.png',
    'index.html',
    'style.css',
  ]);
  for (const icon of ['favicon-16.png', 'favicon-32.png']) {
    assert.deepEqual([...readFileSync(join(out, icon)).subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47]);
  }
  assert.equal(file('style.css'), readFileSync(join(root, 'page/src/style.css'), 'utf8'));
});

test('index.html has no inline script or style and asks no other host', () => {
  const html = file('index.html');
  assert.deepEqual(html.match(/<script[^>]*>/g), ['<script src="/app.js" defer>']);
  assert.equal(/<script[^>]*>[^<]/.test(html), false);
  assert.equal(/<style|\sstyle=|\son[a-z]+=/.test(html), false);
  assert.deepEqual(html.match(/https?:\/\/[^"'\s<>]+/g), [CANONICAL_URL, HOME_URL, HOME_URL]);
  assert.match(html, /<link rel="canonical" href="https:\/\/status\.snowlightmap\.com\/">/);
  assert.match(html, /<a class="home" href="https:\/\/snowlightmap\.com\/">/);
  assert.deepEqual(html.match(/<link[^>]*>/g), [
    '<link rel="canonical" href="https://status.snowlightmap.com/">',
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">',
    '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">',
    '<link rel="stylesheet" href="/style.css">',
  ]);
  assert.equal(/font-face|woff|fonts\./.test(html + file('style.css')), false);
  assert.equal(/<img|<iframe|<object|<embed|<form/.test(html), false);
});

test('the first paint is the same boxes saying Checking', () => {
  const html = file('index.html');
  const wait = mainHtml(viewOf({ kind: 'wait' }));
  // The first paint waits: its footer is drawn once the page fills in (main.wait).
  assert.equal(html.includes(`<main id="main" class="wait">${wait}</main>`), true);
  assert.equal(html, pageHtml(wait));
  assert.match(
    html,
    /<h1><svg class="tile"[^]*<\/svg><span class="brand">Snowlight<\/span> <span class="page">Status<\/span><\/h1>/,
  );
  // "Past problems" is drawn only once there is a problem day, or why none can be listed.
  assert.deepEqual(html.match(/<h2[^>]*>[^<]*<\/h2>/g)?.map(plain), [
    '<h2 id="h-now">Current status</h2>',
  ]);
  // The way back to the website is in the header and in the footer.
  assert.match(html, /<a class="go" href="https:\/\/snowlightmap\.com\/">Go to Snowlight<\/a>/);
  assert.match(html, /<p class="sr" id="said" role="status"><\/p>/);
  // If the script never starts, the stylesheet draws this line in the lead's place.
  assert.match(
    html,
    /<div class="swap"><div><p class="lead">Checking…<\/p><\/div><div class="stuck"><p class="lead">This page did not finish loading\.<\/p><p class="more">Reload it to try again\.<\/p><\/div><\/div>/,
  );
  for (const kind of ['unreachable', 'data'] as const) {
    const other = mainHtml(
      viewOf(
        kind === 'data'
          ? {
              kind,
              summary: null,
              clock: 0,
              kept: false,
              expanded: false,
              picked: null,
            }
          : { kind },
      ),
    );
    assert.equal(/stuck|swap/.test(other), false, kind);
  }
  assert.match(html, /<footer><div class="foot-in"><p class="how">/);
  // A key to every color of bar, the two greys apart.
  assert.deepEqual(
    [...html.matchAll(/<li><span class="sw b-([a-z]+)"><\/span>([^<]*)<\/li>/g)].map((m) => [
      m[1],
      plain(m[2]!),
    ]),
    [
      ['ok', 'Working'],
      ['late', 'Slow or late'],
      ['down', 'Not working'],
      ['none', 'Not checked'],
      ['before', 'Before checks began'],
    ],
  );
  assert.match(
    html,
    /<noscript><p class="noscript">Turn on JavaScript to see the status\.<\/p><\/noscript>/,
  );
  // The lockup's ids are kept, and each id is on the page once.
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ['lk-tile', 'lk-sky', 'lk-snow', 'lk-arm', 'lk-foot', 'lk-above'])
    assert.equal(ids.includes(id), true, id);
});

const OK_ALL = {
  site: 'ok',
  closings: 'ok',
  chances: 'ok',
  accounts: 'ok',
} as const;

/** Every leaf of the copy, as [key, text]. */
function leaves(node: unknown, path = ''): [string, string][] {
  if (typeof node === 'string') return [[path, node]];
  return Object.entries(node as Record<string, unknown>).flatMap(([key, value]) =>
    leaves(value, path === '' ? key : `${path}.${key}`),
  );
}

const escaped = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
/** A sentence of the copy as a pattern: each `{…}` is some filled-in text. */
const pattern = (text: string): RegExp =>
  new RegExp(
    `^${text
      .split(/\{\w+\}/)
      .map(escaped)
      .join('.+')}$`,
  );

/** The text a reader meets: text nodes, and the names given to pictures. */
function texts(html: string): string[] {
  const found: string[] = [];
  for (const [, value] of html.matchAll(/\s(?:aria-label|title|content)="([^"]*)"/g))
    found.push(value!);
  // A name's box in the headline is part of the headline's text. The box keeps its words on
  // one line wherever they fit on one (it is an inline block), so its spaces are read as tied.
  // A length of two parts is a box of two boxes, read the same way; an address's <wbr> is in
  // its box.
  const unbox = (text: string): string =>
    text.replace(/<span class="n[mb]">([^<]*)<\/span>/g, (_, words: string) =>
      words.replace(/ /g, '\u00a0'),
    );
  const body = unbox(
    unbox(
      html
        .replace(/<svg[^]*?<\/svg>/g, '')
        .replace(/<(script|style)[^]*?<\/\1>/g, '')
        .replace(/<wbr>/g, ''),
    ),
  );
  // A day's date in "Past problems" is data, not copy: it is checked for its form instead.
  const dated = body.replace(/<time>([^<]*)<\/time>/g, (_, date: string) => {
    assert.match(date, /^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2}\u00a0\d{1,2}$/);
    return '';
  });
  for (const piece of dated.split(/<[^>]*>/)) found.push(piece);
  return found
    .map((text) =>
      text
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
        .trim(),
    )
    .filter(
      (text) =>
        text !== '' && text !== 'width=device-width, initial-scale=1' && text !== 'light dark',
    );
}

test('in every state each text of the page is made from the copy, and all of the copy is used', () => {
  const NOW = Date.UTC(2026, 10, 10, 15, 0, 0) / 1000;
  const data = (summary: Summary | null, more: object = {}): Input => ({
    kind: 'data',
    summary,
    clock: NOW + 130,
    kept: false,
    expanded: true,
    picked: null,
    zone: 'America/New_York',
    ...more,
  });
  const bad = worst(NOW);
  const unknown: Summary = {
    ...allOk(NOW),
    parts: {
      site: { s: 'unknown' },
      closings: { s: 'ok' },
      chances: { s: 'ok' },
      accounts: { s: 'ok' },
    },
  };
  const young = history(NOW);
  const quiet: Summary = { ...young, incidents: [], parts: allOk(NOW).parts };
  const hourOld: Summary = {
    ...quiet,
    parts: {
      ...quiet.parts,
      closings: { s: 'ok', made: NOW - 3700 },
      chances: { s: 'ok', made: NOW - 2 * 3600 - 300 },
    },
  };
  const daysOld: Summary = {
    ...quiet,
    parts: { ...quiet.parts, chances: { s: 'down', made: NOW - 3 * DAY } },
  };
  const inputs: Input[] = [
    { kind: 'wait' },
    { kind: 'unreachable' },
    data(null),
    data(allOk(NOW)),
    data(young, { picked: { part: 'closings', day: 79 } }),
    data(young, { expanded: false, kept: true }),
    data(young, { clock: NOW + 2000 }),
    data(bad, { picked: { part: 'closings', day: 67 } }),
    data(bad, { expanded: false }),
    data(bad, { picked: { part: 'chances', day: 66 } }),
    data(unknown),
    data(quiet, { picked: { part: 'site', day: 10 } }),
    data(quiet, { picked: { part: 'site', day: 89 } }),
    data(quiet, { picked: { part: 'site', day: 60 } }),
    data(hourOld, { clock: NOW + 40 }),
    data(daysOld),
    data({ ...quiet, first: NOW - 60 * DAY + 3600 }, { picked: { part: 'site', day: 30 } }),
  ];
  // A made-up day with no readings at all, one late for a minute's worth, and long problems.
  const odd: Summary = structuredClone(quiet);
  odd.days.site[50] = [0, 0, 0];
  odd.days.site[51] = [287, 1, 0];
  odd.incidents = [
    { p: 'site', k: 'down', s: NOW - 3 * DAY - 3600, e: NOW - 300, g: 0 },
    { p: 'site', k: 'late', s: NOW - 3660, e: NOW - 3600, g: 0 },
    { p: 'site', k: 'late', s: NOW - 5 * DAY, e: NOW - 5 * DAY + DAY, g: 1 },
  ];
  inputs.push(
    data(odd, { picked: { part: 'site', day: 50 } }),
    data(odd, { picked: { part: 'site', day: 51 } }),
  );
  // Checks that began an hour ago, read a minute after the last one.
  const hour = simulate(NOW - 3600, NOW, () => OK_ALL);
  inputs.push(
    data(hour, { clock: NOW + 70 }),
    data(hour, { clock: NOW + 70, picked: { part: 'site', day: 89 } }),
  );
  // Two minutes into a new UTC day, before its first check is in; and summaries days old.
  const midnight = Math.floor(NOW / DAY) * DAY;
  const eve = simulate(midnight - 2 * DAY, midnight - 300, () => OK_ALL);
  inputs.push(
    data(eve, { clock: midnight + 120, picked: { part: 'site', day: 89 } }),
    // 88 days later only the second of its two days is still a bar: "over 1 day".
    data(eve, { clock: midnight + 88 * DAY + 3600 }),
    data(young, {
      clock: NOW + DAY + 7200,
      picked: { part: 'chances', day: 89 },
    }),
    data(bad, {
      clock: NOW + 3 * DAY + 7200,
      picked: { part: 'closings', day: 86 },
    }),
  );
  // A summary that is full: it holds only the newest problems.
  const flap: Summary = structuredClone(quiet);
  flap.incidents = Array.from({ length: INCIDENTS_MAX }, (_, i) => ({
    p: 'site' as const,
    k: 'late' as const,
    s: NOW - 3600 - i * 1200,
    e: NOW - 3600 - i * 1200 + 300,
    g: 0 as const,
  }));
  flap.days.site = flap.days.site.map((day, i) => (i > 85 ? [day[0] - 30, 30, 0] : day));
  inputs.push(data(flap));
  // A day the checker missed, and a quiet summary gone stale.
  const gappy: Summary = structuredClone(quiet);
  gappy.days.site[85] = [0, 0, 0];
  inputs.push(data(gappy), data(allOk(NOW), { clock: NOW + 2000 }));
  // Launch day (one part never answered), a quiet summary a day old, and one 100 days old.
  inputs.push(
    data(launch(NOW)),
    data(quiet, { clock: NOW + DAY }),
    data(young, { clock: NOW + 100 * DAY, picked: { part: 'site', day: 89 } }),
  );

  const all = leaves(copy);
  const patterns = all.map(([key, text]) => [key, pattern(text)] as const);
  const used = new Set<string>();
  // What a screen reader is told when the headline changes is copy too.
  const read = (input: Input): string[] => [
    ...texts(pageHtml(mainHtml(viewOf(input)))),
    viewOf(input).banner.said,
  ];
  for (const input of inputs) {
    for (const text of read(input)) {
      const hits = patterns.filter(([, made]) => made.test(text));
      assert.equal(hits.length > 0, true, `not from the copy: "${text}"`);
      for (const [key] of hits) used.add(key);
    }
  }
  // The pieces a sentence is filled with are used when a sentence that holds them is.
  const pieces = new Map([
    ['list.and', / and /],
    ['list.comma', /, /],
    ['dur.two', /\d (?:hours?|days?) \d/],
    ['dur.minute', /\b1 minute\b/],
    ['dur.minutes', /\d minutes\b/],
    ['dur.hour', /\b1 hour\b/],
    ['dur.hours', /\d hours\b/],
    ['dur.day', /\b1 day\b/],
    ['dur.days', /\d days\b/],
    ['ago.now', /just now/],
    ['ago.minute', /\b1 minute ago/],
    ['ago.minutes', /\d minutes ago/],
    ['ago.hour', /\b1 hour ago/],
    ['ago.hours', /\d hours ago/],
    ['ago.days', /\d days ago/],
    ['day.down', /: not working for |, not working for /],
    ['day.late', /slow or late for \d/],
    ['day.gap', /, not checked for /],
    ['problem.down', /: not working (?:for|since)/],
    ['problem.late', /: slow or late (?:for|since)/],
  ]);
  const everything = plain(inputs.map((input) => read(input).join('\n')).join('\n'));
  for (const [key, shows] of pieces) if (shows.test(everything)) used.add(key);
  assert.deepEqual(
    all.map(([key]) => key).filter((key) => !used.has(key)),
    [],
  );

  // In every state: the lines drawn with tabular numbers never hold a hyphen (those numbers
  // widen it), no state draws "Past problems" with nothing under it, and no sentence says
  // "today" of a day that is not the clock's.
  let hidden = 0;
  for (const input of inputs) {
    const html = mainHtml(viewOf(input));
    // A name's or a tied run's box is read as part of its text.
    const flat = html.replace(/<span class="n[mb]">([^<]*)<\/span>/g, '$1');
    const tabular = [...flat.matchAll(/<(?:p|span) class="(?:more|upd|share|mid|when)">([^<]*)</g)];
    assert.equal(tabular.length > 0, true);
    for (const [, text] of tabular) assert.equal(/[-‐‑]/.test(text!), false, text);
    const names = [...flat.matchAll(/<span class="name">([^<]*)</g)].map((m) => m[1]);
    assert.equal(names.map((name) => plain(name!)).includes('Snow-day chances'), true);
    if (!html.includes('id="h-problems"')) hidden += 1;
    else {
      const box = /<p class="(?:empty|none|what k-\w+)">([^<]+)</.exec(flat);
      assert.notEqual(box, null, 'nothing under Past problems');
      // Every day listed says something: its problems, or why it has none.
      for (const day of flat.matchAll(
        /<li class="day">([^]*?)<\/li><\/(?:ol|ul)>|<li class="day">([^]*?)(?=<li class="day">)/g,
      )) {
        assert.match(day[0], /class="(?:none|what k-\w+)">[^<]+</);
      }
    }
    if (input.kind === 'data' && input.summary !== null) {
      const clockDay = new Date(Math.max(input.clock, input.summary.now) * 1000)
        .toUTCString()
        .slice(0, 11)
        .replace(/^(\w+), 0?(\d+) (\w+)$/, '$1, $3 $2');
      for (const [, label] of html.matchAll(/aria-label="([^"]*today[^"]*)"/g))
        assert.equal(plain(label!).startsWith(`${clockDay}:`), true, `${label} on ${clockDay}`);
    }
  }
  // The page as it waits, and every state with no problem day, draw no "Past problems".
  assert.equal(hidden > 1, true);
  assert.equal(mainHtml(viewOf(data(allOk(NOW)))).includes('Past problems'), false);
});

test('no line of the page can break inside a name, a date, a time or a count', () => {
  // The copy itself: every number is tied to its word and every hyphen in a name to the next.
  for (const [key, text] of leaves(copy)) assert.deepEqual(breaks(text), [], key);
  assert.equal(copy.parts.chances.name, 'Snow-\u2060day\u00a0chances');
  // A part's name holds no space a line may break at, wherever it is drawn.
  for (const part of Object.values(copy.parts)) assert.doesNotMatch(part.name, /[ \t\n]/);
  assert.deepEqual(breaks('Website, Live school closings, for at least 5\u00a0minutes'), [
    'Live school',
    'at least',
  ]);
  assert.deepEqual(breaks('5 minutes, Nov 10, 2:35\u00a0PM EST, Snow-day'), [
    '5 minutes',
    'Nov 10',
    'PM EST',
    'Snow-day',
  ]);
  assert.deepEqual(breaks('42\u00a0minutes ago, just now, 1\u00a0hour 10\u00a0minutes'), [
    'minutes ago',
    'just now',
    'hour 10',
  ]);

  // And every text the page draws, in every state, in zones whose times are written apart.
  const NOW = Date.UTC(2026, 10, 10, 15, 0, 0) / 1000;
  const summaries = [history(NOW), worst(NOW), allOk(NOW), launch(NOW)];
  let seen = 0;
  for (const summary of summaries) {
    for (const zone of ['America/New_York', 'America/Los_Angeles', 'Europe/Paris', 'UTC']) {
      for (const clock of [NOW + 130, NOW + 2000, NOW + 3 * DAY, NOW + 100 * DAY]) {
        for (const day of [0, 30, 66, 67, 79, 86, 89]) {
          const input: Input = {
            kind: 'data',
            summary,
            clock,
            kept: false,
            expanded: true,
            picked: { part: day % 2 === 0 ? 'closings' : 'chances', day },
            zone,
          };
          for (const text of texts(pageHtml(mainHtml(viewOf(input))))) {
            assert.deepEqual(breaks(text), [], text);
            seen += 1;
          }
        }
      }
    }
  }
  assert.equal(seen > 50000, true, String(seen));
  // What ties them is in the words themselves, so it holds in every typeface and at every width.
  const html = mainHtml(
    viewOf({
      kind: 'data',
      summary: history(NOW),
      clock: NOW + 130,
      kept: false,
      expanded: true,
      picked: { part: 'closings', day: 79 },
      zone: 'America/New_York',
    }),
  );
  assert.match(
    html,
    /<p class="what k-late"><span class="nm">Snow-\u2060day chances:<\/span> slow or late since <span class="nb">Nov 10,<\/span> <span class="nb">8:55 AM EST\.<\/span>/,
  );
  const worstHtml = mainHtml(
    viewOf({
      kind: 'data',
      summary: worst(NOW),
      clock: NOW + 130,
      kept: false,
      expanded: true,
      picked: null,
      zone: 'America/New_York',
    }),
  );
  assert.match(
    worstHtml,
    /for <span class="nb">at least<\/span> <span class="nb">(?:<span class="nb">)?\d/,
  );
  // A length of two parts is a box of two boxes: where it is wider than the line it breaks
  // between its parts, never between a number and its unit.
  assert.match(
    worstHtml,
    /<span class="nb"><span class="nb">\d+ hours?<\/span> <span class="nb">\d+ minutes?\.<\/span><\/span>/,
  );
  assert.doesNotMatch(worstHtml, /\u202f/);
  // The address is a box that breaks only at its dot.
  assert.match(
    worstHtml,
    /<span class="about" aria-hidden="true">Opening <span class="nb">snowlightmap<wbr>\.com\.<\/span><\/span>/,
  );
  // The same boxes hold each name in the card and in the problems.
  assert.match(
    worstHtml,
    /<p class="top"><span class="name"><span class="nm">Live school closings<\/span><\/span>/,
  );
  assert.match(worstHtml, /<p class="what k-down"><span class="nm">Live school closings:<\/span> /);
  // A picked day's name is in the tip, with its length of two parts a box of two boxes.
  const tipped = mainHtml(
    viewOf({
      kind: 'data',
      summary: history(NOW),
      clock: NOW + 130,
      kept: false,
      expanded: false,
      picked: { part: 'closings', day: 79 },
      zone: 'America/New_York',
    }),
  );
  assert.match(
    tipped,
    /<p class="tip" id="tip" role="tooltip"><span class="nb">Oct 30,<\/span> <span class="nb">8:00 PM to<\/span> <span class="nb">Oct 31,<\/span> <span class="nb">8:00 PM EDT:<\/span> not working for <span class="nb">15 minutes,<\/span> not checked for <span class="nb">6 hours\.<\/span><\/p>/,
  );
  assert.match(
    html,
    /aria-label="Oct\u00a030, 8:00\u00a0PM\u00a0to Oct\u00a031, 8:00\u00a0PM\u00a0EDT: [^"]*not checked for 6\u00a0hours\."/,
  );
});

test('every kind of bar has its own drawing, and a day with nothing to show is a full grey bar', () => {
  const css = file('style.css');
  for (const cls of ['b-ok', 'b-late', 'b-down', 'b-none', 'b-before', 'b-wait', 'b-yet'])
    assert.equal(css.includes(`.${cls}`), true, cls);
  const flat = css.replace(/\/\*[^]*?\*\//g, '').replace(/\s+/g, ' ');
  assert.match(flat, /\.b-before, \.b-wait, \.b-yet \{ background: var\(--before\); \}/);
  // No bar is drawn shorter than its row: the row always looks whole.
  assert.equal(/\.b-[a-z]+ \{[^}]*block-size/.test(flat), false);
});

test('coming back to the page draws on the clock before it fetches', () => {
  const source = readFileSync(join(root, 'page/src/app.ts'), 'utf8');
  // One function for both ways back, and its first act is to draw.
  assert.match(source, /function back\(\): void \{\n  draw\(\);\n  refreshIfDue\(/);
  assert.match(
    source,
    /addEventListener\('visibilitychange', \(\) => \{\n  if \(document\.visibilityState === 'visible'\) back\(\);/,
  );
  assert.match(source, /window\.addEventListener\('pageshow', back\);/);
  assert.equal(source.match(/refreshIfDue\(/g)?.length, 3);
});

test('every value is escaped', () => {
  const summary = allOk(Date.UTC(2026, 10, 10, 15, 0, 0) / 1000);
  const view = viewOf({
    kind: 'data',
    summary,
    clock: summary.now,
    kept: false,
    expanded: false,
    picked: null,
  });
  view.banner.lead = '<img src=x onerror=alert(1)> & "quotes"';
  view.history[0]!.bars[0]!.label = '"><script>alert(1)</script>';
  const html = mainHtml(view);
  assert.equal(html.includes('<img'), false);
  assert.equal(html.includes('<script>'), false);
  assert.equal(html.includes('&lt;img src=x onerror=alert(1)&gt; &amp; &quot;quotes&quot;'), true);
});

test('the headers and the routes are the ones the page needs', () => {
  assert.equal(
    file('_headers'),
    "/*\n  Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\n" +
      '  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n  X-Robots-Tag: noindex\n',
  );
  assert.deepEqual(JSON.parse(file('_routes.json')), {
    version: 1,
    include: ['/api/*'],
    exclude: [],
  });
});

test('the script is small, asks only its own origin, and keeps nothing', () => {
  const script = file('app.js');
  // Past problems reads each day against its bars, the summary's runs of unanswered checks and
  // its cut, and each tip names its span in the reader's zone: 24 KB at most.
  assert.equal(Buffer.byteLength(script) <= 24000, true, String(Buffer.byteLength(script)));
  assert.deepEqual(script.match(/fetch\(("[^"]*")/g), ['fetch("/api/status"']);
  assert.match(script, /credentials:"omit"/);
  // A reload is never answered from the browser's cache, which would set the clock back.
  assert.match(script, /fetch\("\/api\/status",\{cache:"no-store",credentials:"omit"/);
  assert.equal(
    /localStorage|sessionStorage|document\.cookie|indexedDB|sendBeacon|XMLHttpRequest|WebSocket|eval\(|new Function/.test(
      script,
    ),
    false,
  );
  assert.deepEqual(script.match(/https?:\/\/[a-z0-9.-]+/g) ?? [], []);
});

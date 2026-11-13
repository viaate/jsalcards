// gen-golden.mjs: the iPhone app's golden answers, made by running the site's own code.
//
//   node ios/tools/gen-golden.mjs            write the golden files
//   node ios/tools/gen-golden.mjs --check    write nothing; compare with what is committed
//
// It imports the site's modules (web/src) through node-hooks.mjs, runs each family's
// cases, and writes ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/golden/<family>.json,
// and the app's list of time zone names, ios/SnowlightCore/Sources/SnowlightCore/Files/
// ZoneNames.swift. The Swift tests must give the same answers, character for character.
// The closings, predictions and season cases read the copies of the pipeline's synthetic
// files in Fixtures/site/ (sync-fixtures.mjs): run that first.
//
// Every answer comes from the site's code. This script never builds a sentence itself.
//
// A golden file is
//   {"family", "min_cases", "made_from": [{"path", "sha256"} for each site file loaded],
//    "cases": [one case per line]}
// written with sorted keys, ASCII only, a fixed order and no time stamp, so two runs give
// the same bytes on any machine and in any time zone.
//
// --check compares answers, not files: `family`, `min_cases` and `cases`. A site file whose
// bytes changed while every answer stayed the same (a comment, say) is printed as a note
// and fails nothing. The zone list is compared whole.
//
// Exit codes:
//   0  everything matches (or, when writing, everything was written)
//   1  an answer differs from the committed golden files, or a family is below its minimum
//   2  the site's code could not be loaded or run
//   3  Node is older than 22.18, or the arguments are wrong
//   4  a site file that was loaded lies outside what the words watch covers
//
// Node's built-in modules only: it needs no `npm ci`.

// A site function that leaned on the machine's time zone must show up as a difference, so
// this never runs on a UTC clock. CI runs it under two odd zones.
if (process.env.TZ === undefined || process.env.TZ === '' || process.env.TZ === 'UTC') {
  process.env.TZ = 'America/St_Johns';
}

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EXIT_DIFFERS = 1;
const EXIT_CANNOT_LOAD = 2;
const EXIT_USAGE = 3;
const EXIT_OUTSIDE_WATCH = 4;

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');
const FIXTURES = join(REPO, 'ios', 'SnowlightCore', 'Tests', 'SnowlightCoreTests', 'Fixtures');
const GOLDEN = join(FIXTURES, 'golden');
/** The copies of the pipeline's synthetic files (sync-fixtures.mjs): the files the Swift tests read. */
const SITE_FIXTURES = join(FIXTURES, 'site');
/** The app's list of time zone names (item 27), a Swift source written here and compared whole. */
const ZONE_NAMES = join(REPO, 'ios', 'SnowlightCore', 'Sources', 'SnowlightCore', 'Files', 'ZoneNames.swift');

/**
 * What the words watch (.github/workflows/ios-words-watch.yml) covers. A site file loaded
 * from anywhere else could change without the watch running, so that is refused.
 */
const WATCHED_FOLDER = 'web/src/';
const WATCHED_FILES = ['web/scripts/check-copy.mjs'];

// Inputs ---------------------------------------------------------------------------------
//
// Everything in this part makes INPUTS only: instants, days, texts, mutated files. No answer
// is ever made here. Every answer in a golden file is what a site function returned.

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/** A site function's answer, or the mark that it threw. Only RangeError is the site refusing. */
const THROWS = Object.freeze({ throws: true });
function answer(call) {
  try {
    return call();
  } catch (error) {
    if (error instanceof RangeError) return THROWS;
    throw error;
  }
}

/** A number as an input: JSON cannot hold NaN or the infinities, so those are written as text. */
function num(value) {
  if (Number.isNaN(value)) return 'NaN';
  if (value === Infinity) return 'Infinity';
  if (value === -Infinity) return '-Infinity';
  return value;
}

/** An instant (a Date the site returned, or one given) as whole milliseconds; null stays null. */
function ms(date) {
  if (date === null) return null;
  return num(date.getTime());
}

/** A JSON copy, so a mutation never changes the fixture it starts from. */
function copyOf(value) {
  return JSON.parse(JSON.stringify(value));
}

/** The four text traps (TT), each applied to an otherwise good value. */
const TEXT_TRAPS = [
  ['full-width digits', (text) => text.replace(/[0-9]/g, (d) => String.fromCharCode(0xff10 + Number(d)))],
  ['Arabic-Indic digits', (text) => text.replace(/[0-9]/g, (d) => String.fromCharCode(0x0660 + Number(d)))],
  ['a trailing newline', (text) => `${text}\n`],
  ['a leading U+FEFF', (text) => `﻿${text}`],
];
const trapped = (text) => TEXT_TRAPS.map(([, trap]) => trap(text));

/** A small fixed pseudo-random sequence, so the larger sets are the same on every run. */
function sequence(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296;
  };
}

/** The wall clock of an instant on a zone's clock, as that day and time counted in UTC. */
const wallFormats = new Map();
function wallMs(at, zone) {
  let formatter = wallFormats.get(zone);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
    wallFormats.set(zone, formatter);
  }
  const parts = Object.fromEntries(formatter.formatToParts(new Date(at)).map((p) => [p.type, p.value]));
  return Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour) % 24, Number(parts.minute), Number(parts.second));
}

/** The calendar day an instant falls on, on a zone's clock. */
function wallDay(at, zone) {
  return new Date(wallMs(at, zone)).toISOString().slice(0, 10);
}

/** The instant a day's minute strikes on a zone's clock (an input to the site, never an answer). */
function atLocal(day, minute, zone) {
  const target = Date.parse(`${day}T00:00:00Z`) + minute * MINUTE_MS;
  let at = target;
  for (let i = 0; i < 3; i += 1) at += target - wallMs(at, zone);
  return at;
}

function addDays(day, n) {
  return new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10);
}

/** Z8: the zones the time of day is said in. */
const Z8 = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'UTC',
];
/** Z10: the seven US zones, no zone, the unread zone and the unknown zone. */
const Z10 = [...Z8.slice(0, 7), null, '*', '?'];
/** The five viewer zones the stamps and the status lines are told in. */
const Z5 = ['America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'Pacific/Honolulu'];
/** ZX: the odd zone names. */
const ZX = [
  'america/chicago',
  'AMERICA/CHICAGO',
  'US/Central',
  'EST',
  'PST',
  'CDT',
  'EST5EDT',
  'GMT',
  'GMT+5',
  'GMT+0500',
  'UTC+5',
  '+05:00',
  '-0600',
  'Etc/GMT+5',
  'Etc/Unknown',
  'Z',
  'America/Kiev',
  'Europe/Kiev',
  'Europe/Kyiv',
  'America/Indianapolis',
  'America/Indiana/Indianapolis',
  'America/Louisville',
  'America/Kentucky/Louisville',
  ' America/Chicago',
  'America/Chicago ',
  'America/Chicago\n',
  '',
  'Mars/Olympus',
];
/** W3: three 72-hour windows, by their first instant. */
const W3 = ['2026-10-31T00:00:00Z', '2027-03-13T00:00:00Z', '2027-01-11T00:00:00Z'].map((text) => Date.parse(text));
const WINDOW_MS = 72 * HOUR_MS;

/** The long US spellings Node's list leaves out (it lists the short ones); the site's region table uses these. */
const LONG_US_ZONES = ['America/Indiana/Indianapolis', 'America/Kentucky/Louisville'];
/** How many names on the list have a region other than `other`: the size of the site's region table today. */
const REGIONED_ZONES = 28;

/**
 * The zone list (item 27): Node's own zone names, UTC and the long US spellings, each kept only
 * if the site's isTimeZone accepts it, so the list is never wider than the site.
 * @returns {string[]} sorted
 */
function zoneList(mapDay) {
  const candidates = new Set([...Intl.supportedValuesOf('timeZone'), 'UTC', ...LONG_US_ZONES]);
  const kept = [...candidates].filter((name) => mapDay.isTimeZone(name)).sort();
  // Written into a Swift source as plain literals: only letters, digits and _ + - /.
  const odd = kept.filter((name) => !/^[A-Za-z0-9_+\-/]+$/.test(name));
  if (odd.length > 0) throw new Stop(EXIT_CANNOT_LOAD, `zone names a Swift literal would not hold as written: ${odd.join(', ')}`);
  const regioned = kept.filter((name) => mapDay.regionOf(name) !== 'other');
  if (regioned.length !== REGIONED_ZONES) {
    throw new Stop(
      EXIT_CANNOT_LOAD,
      `the zone list has ${regioned.length} names with a region, not ${REGIONED_ZONES}: the site's region table changed (web/src/data/map-day.ts regionOf). Look at the list again (item 27) before changing REGIONED_ZONES`,
    );
  }
  return kept;
}

/** Whether the site accepted a zone name the app's list does not hold: there the app must refuse. */
function narrowerZone(zone, onList, mapDay) {
  return typeof zone === 'string' && zone !== '*' && zone !== '?' && !onList.has(zone) && mapDay.isTimeZone(zone);
}

/** A fixture copy (Fixtures/site/...), read as JSON. */
function fixture(path) {
  const file = join(SITE_FIXTURES, ...path.split('/'));
  if (!existsSync(file)) {
    throw new Stop(EXIT_USAGE, `the fixture copy site/${path} is missing: copy the fixtures first (node ios/tools/sync-fixtures.mjs)`);
  }
  return JSON.parse(readFileSync(file, 'utf8'));
}

/**
 * Applies one change to a copy of a file: `path` is a list of keys and positions, and the
 * value is set there (or the key is removed, for REMOVE).
 */
const REMOVE = Symbol('remove');
function changed(base, path, value) {
  const copy = copyOf(base);
  let here = copy;
  for (const key of path.slice(0, -1)) here = here[key];
  const last = path[path.length - 1];
  if (value === REMOVE) {
    if (Array.isArray(here)) here.splice(last, 1);
    else delete here[last];
  } else {
    here[last] = value;
  }
  return copy;
}

/** A file made by a function of a copy (for changes that are not one key's value). */
function made(base, change) {
  const copy = copyOf(base);
  change(copy);
  return copy;
}

// The families -----------------------------------------------------------------------------
//
// Each case is one line: an array whose first entries are the inputs and whose last entries
// are the site's answers, in the order the family's comment gives. Where a family holds more
// than one kind of case, the first entry names the kind. Instants are whole milliseconds since
// 1970 (UTC); days are YYYY-MM-DD; {"throws": true} is the site refusing (a RangeError), apart
// from null, the site saying nothing. A number input JSON cannot hold is the text "NaN",
// "Infinity" or "-Infinity".

/** The closings rows a file holds for a school on a day, as rowOn gives them. */
function rowCase(row) {
  if (row === null) return null;
  return [row.status, row.reason, ms(row.announcedAt), row.shiftMinutes, row.clockMinute, row.manual, [...row.details]];
}

/** The 22 detail codes of the closings file's details column (the site's DETAIL_COUNT). */
const DETAIL_CODES = 22;

const FAMILIES = [
  {
    // The site's fixed words, as they are: one case, {copy, detailsCopy, chanceCopy: {noSchool}}.
    family: 'copy',
    minCases: 1,
    modules: ['copy.ts', 'copy-details.ts', 'copy-chance.ts'],
    cases: (site) => [
      {
        copy: site['copy.ts'].copy,
        detailsCopy: site['copy-details.ts'].detailsCopy,
        chanceCopy: { noSchool: site['copy-chance.ts'].chanceCopy.noSchool },
      },
    ],
  },
  {
    // [minute, format.clock(minute)]
    family: 'clock',
    minCases: 1443,
    modules: ['copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const minutes = [...Array.from({ length: 1440 }, (_, m) => m), 1440, -1, 1.5];
      return minutes.map((m) => [num(m), answer(() => format.clock(m))]);
    },
  },
  {
    // [instant, zone, format.time(instant, zone)]: every 37 minutes over W3 in each zone of Z8,
    // then an invalid instant and a zone no clock knows.
    family: 'time',
    minCases: 2500,
    modules: ['copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const cases = [];
      for (const zone of Z8) {
        for (const start of W3) {
          for (let at = start; at < start + WINDOW_MS; at += 37 * MINUTE_MS) {
            cases.push([at, zone, answer(() => format.time(new Date(at), zone))]);
          }
        }
      }
      cases.push([num(NaN), 'America/Chicago', answer(() => format.time(new Date(NaN), 'America/Chicago'))]);
      cases.push([W3[0], 'Mars/Olympus', answer(() => format.time(new Date(W3[0]), 'Mars/Olympus'))]);
      return cases;
    },
  },
  {
    // [text, parseInstant(text)]: the answer is the instant, or null.
    family: 'instant',
    minCases: 50,
    modules: ['state/instant.ts'],
    cases: (site) => {
      const { parseInstant } = site['state/instant.ts'];
      const good = [
        '1970-01-01T00:00:00Z',
        '0000-01-01T00:00:00Z',
        '0001-12-31T23:59:59Z',
        '1969-12-31T23:59:59Z',
        '1999-12-31T23:59:59Z',
        '2000-02-29T12:00:00Z',
        '2024-02-29T00:00:00Z',
        '2028-02-29T23:59:59Z',
        '2026-01-01T00:00:00Z',
        '2026-07-01T04:00:00Z',
        '2026-10-31T23:59:59Z',
        '2026-11-01T05:59:59Z',
        '2026-11-01T06:00:00Z',
        '2026-11-01T07:00:00Z',
        '2026-12-31T23:59:59Z',
        '2027-01-11T23:00:00Z',
        '2027-01-12T11:00:00Z',
        '2027-01-12T13:05:00Z',
        '2027-01-12T21:30:00Z',
        '2027-01-13T05:59:00Z',
        '2027-03-14T06:59:59Z',
        '2027-03-14T07:00:00Z',
        '2027-03-14T10:00:00Z',
        '2027-04-30T12:34:56Z',
        '2027-06-30T23:59:59Z',
        '2027-12-31T23:59:59Z',
        '2038-01-19T03:14:08Z',
        '2100-03-01T00:00:00Z',
        '2400-02-29T00:00:00Z',
        '9999-12-31T23:59:59Z',
      ];
      const bad = [
        '2027-02-30T00:00:00Z',
        '2027-13-01T00:00:00Z',
        '2027-01-00T00:00:00Z',
        '2027-01-32T00:00:00Z',
        '2027-01-12T24:00:00Z',
        '2027-01-12T13:60:00Z',
        '2027-01-12T13:05:60Z',
        '2027-01-12T13:05:00',
        '2027-01-12T13:05:00z',
        '2027-01-12t13:05:00Z',
        '2027-01-12T13:05:00+00:00',
        '2027-01-12T13:05:00.000Z',
      ];
      const traps = ['2027-01-12T13:05:00Z', '2026-11-01T06:00:00Z'].flatMap(trapped);
      return [...good, ...bad, ...traps].map((text) => [text, ms(parseInstant(text))]);
    },
  },
  {
    // [text, format.day, format.dayWithYear, chanceFormat.weekday, chanceFormat.chanceOn]
    family: 'days',
    minCases: 373,
    modules: ['copy-format.ts', 'copy-chance.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const { chanceFormat } = site['copy-chance.ts'];
      const texts = [];
      for (let day = '2026-07-01'; day <= '2027-06-30'; day = addDays(day, 1)) texts.push(day);
      texts.push('2026-02-30', '2026-13-01', '26-1-1', 'abc', ...trapped('2027-01-12'));
      return texts.map((text) => [
        text,
        answer(() => format.day(text)),
        answer(() => format.dayWithYear(text)),
        answer(() => chanceFormat.weekday(text)),
        answer(() => chanceFormat.chanceOn(text)),
      ]);
    },
  },
  {
    // [instant, zone, now, format.liveAt(instant, zone), format.updatedAt(instant, zone, now),
    //  format.offline(instant, zone, now), format.posted(instant, zone, now)]: in each viewer zone,
    // four values of now (5 minutes each side of local midnight, and two on the days the clocks
    // change), each with ten instants on now's local day, ten the day before and ten the day after.
    family: 'stamps',
    minCases: 600,
    modules: ['copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const nows = [
        ['2027-01-11', 23 * 60 + 55],
        ['2027-01-12', 5],
        ['2026-11-01', 6 * 60 + 42],
        ['2027-03-14', 15 * 60 + 30],
      ];
      const times = [0, 1, 5 * 60 + 12, 6 * 60 + 42, 9 * 60, 12 * 60, 12 * 60 + 30, 15 * 60 + 30, 20 * 60 + 30, 23 * 60 + 59];
      const cases = [];
      for (const zone of Z5) {
        for (const [nowDay, nowMinute] of nows) {
          const now = atLocal(nowDay, nowMinute, zone);
          for (const offset of [0, -1, 1]) {
            const day = addDays(nowDay, offset);
            for (const minute of times) {
              const at = atLocal(day, minute, zone);
              const instant = new Date(at);
              const when = new Date(now);
              cases.push([
                at,
                zone,
                now,
                answer(() => format.liveAt(instant, zone)),
                answer(() => format.updatedAt(instant, zone, when)),
                answer(() => format.offline(instant, zone, when)),
                answer(() => format.posted(instant, zone, when)),
              ]);
            }
          }
        }
      }
      return cases;
    },
  },
  {
    // [status, day, now, zone, format.statusOn(status, day, now, zone)]: each status, the days
    // -1, 0, 1, 2 and 7 from now's local day, in each viewer zone, at four values of now; then
    // status keys the site does not have.
    family: 'status-on',
    minCases: 400,
    modules: ['copy.ts', 'copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const { STATUS_KEYS } = site['copy.ts'];
      const nows = [
        ['2027-01-11', 23 * 60 + 55],
        ['2027-01-12', 5],
        ['2026-11-01', 15 * 60 + 29],
        ['2027-03-14', 15 * 60 + 31],
      ];
      const cases = [];
      for (const status of STATUS_KEYS) {
        for (const offset of [-1, 0, 1, 2, 7]) {
          for (const zone of Z5) {
            for (const [nowDay, nowMinute] of nows) {
              const now = atLocal(nowDay, nowMinute, zone);
              const day = addDays(wallDay(now, zone), offset);
              cases.push([status, day, now, zone, answer(() => format.statusOn(status, day, new Date(now), zone))]);
            }
          }
        }
      }
      const now = atLocal('2027-01-12', 9 * 60, 'America/Chicago');
      for (const status of ['open', 'toString', 'Closed']) {
        cases.push([status, '2027-01-12', now, 'America/Chicago', answer(() => format.statusOn(status, '2027-01-12', new Date(now), 'America/Chicago'))]);
      }
      return cases;
    },
  },
  {
    // [shift, clock, format.delay(shift, clock), format.dismissal(shift, clock)]
    family: 'shift',
    minCases: 880,
    modules: ['copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const pairs = [];
      for (let shift = 1; shift <= 720; shift += 1) pairs.push([shift, null]);
      const shifts = [null, 1, 2, 15, 30, 45, 59, 60, 61, 75, 89, 90, 91, 105, 119, 120, 121, 135, 150, 180, 210, 240, 330, 720];
      const clocks = [null, 0, 450, 600, 630, 750, 1439];
      for (const shift of shifts) for (const clock of clocks) pairs.push([shift, clock]);
      pairs.push([0, null], [721, null], [1.5, null], [null, 1440], [null, -1], [null, 1.5]);
      return pairs.map(([shift, clock]) => [
        shift === null ? null : num(shift),
        clock === null ? null : num(clock),
        answer(() => format.delay(shift, clock)),
        answer(() => format.dismissal(shift, clock)),
      ]);
    },
  },
  {
    // [p, format.chance(p), chanceFormat.chanceNumber(p), chanceFormat.delayInstead(p)]
    family: 'chance',
    minCases: 200,
    modules: ['copy-format.ts', 'copy-chance.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const { chanceFormat } = site['copy-chance.ts'];
      const ps = [0, 0.001, 0.004, 0.005];
      for (let k = 2; k <= 199; k += 1) ps.push(Number((k * 0.005).toFixed(3)));
      ps.push(0.999, 1, -0.1, 1.1, NaN, Infinity, -Infinity);
      return ps.map((p) => [
        num(p),
        answer(() => format.chance(p)),
        answer(() => chanceFormat.chanceNumber(p)),
        answer(() => chanceFormat.delayInstead(p)),
      ]);
    },
  },
  {
    // ["grades", low, high, format.grades(low, high)] and ["number", n, format.number(n)]
    family: 'grades',
    minCases: 270,
    modules: ['copy-format.ts'],
    cases: (site) => {
      const { format } = site['copy-format.ts'];
      const codes = ['PK', 'TK', 'KG', ...Array.from({ length: 13 }, (_, i) => String(i + 1).padStart(2, '0'))];
      const cases = [];
      for (const low of codes) for (const high of codes) cases.push(['grades', low, high, answer(() => format.grades(low, high))]);
      for (const low of ['00', '14', 'K', ...trapped('01')]) cases.push(['grades', low, '12', answer(() => format.grades(low, '12'))]);
      for (const n of [0, 1, 12, 999, 1000, 1284, 12345, 118211, 1234567, -1, 1.5]) {
        cases.push(['number', num(n), answer(() => format.number(n))]);
      }
      return cases;
    },
  },
  {
    // [codes, detailsFormat.said(codes)]
    family: 'details',
    minCases: 320,
    modules: ['copy-details.ts'],
    cases: (site) => {
      const { detailsFormat } = site['copy-details.ts'];
      const sets = [];
      for (let i = 0; i < DETAIL_CODES; i += 1) sets.push([i]);
      for (let i = 0; i < DETAIL_CODES; i += 1) for (let j = i + 1; j < DETAIL_CODES; j += 1) sets.push([i, j]);
      for (let i = 0; i + 2 < DETAIL_CODES; i += 1) sets.push([i, i + 1, i + 2]);
      // Fifty larger sets, in any order and with repeats, as a column read on another day might hold.
      const next = sequence(20261110);
      for (let k = 0; k < 50; k += 1) {
        const size = 4 + Math.floor(next() * 9);
        sets.push(Array.from({ length: size }, () => Math.floor(next() * DETAIL_CODES)));
      }
      sets.push([], [3, 22, 5], [99, 0]);
      return sets.map((codes) => [codes, answer(() => detailsFormat.said(codes))]);
    },
  },
  {
    // [closed, delayed, remote, earlyDismissal, since, seasonFormat.line(days, since)]
    family: 'season-line',
    minCases: 1000,
    modules: ['copy-season.ts'],
    cases: (site) => {
      const { seasonFormat } = site['copy-season.ts'];
      const counts = [0, 1, 2, 11];
      const cases = [];
      for (const since of [null, '2026-10-26', '2026-10-27', '2027-01-04']) {
        for (const closed of counts) for (const delayed of counts) for (const remote of counts) for (const early of counts) {
          if (closed + delayed + remote + early === 0 && since !== null) continue;
          const days = { closed, delayed, remote, earlyDismissal: early };
          cases.push([closed, delayed, remote, early, since, answer(() => seasonFormat.line(days, since))]);
        }
      }
      return cases;
    },
  },
  {
    // ["file", name, path, json, parseSeason accepts]: the site fixture (path, json null) and
    //   one-change mutations of it (path null, json the file);
    // ["school", school, directory, now, schoolSeason(fixture, school, directory, now)]: the
    //   answer null or [closed, delayed, remote, earlyDismissal, since];
    // ["lastDayOver", now, lastDayOver(now)].
    family: 'season-file',
    minCases: 200,
    modules: ['data/season.ts'],
    cases: (site) => {
      const { parseSeason, schoolSeason, lastDayOver } = site['data/season.ts'];
      const path = 'schemas/examples/synthetic-live-season.json';
      const base = fixture(path);
      const cases = [['file', 'fixture', path, null, parseSeason(copyOf(base)) !== null]];
      const mutations = [
        ['schema 2', changed(base, ['schema_version'], 2)],
        ['schema as text', changed(base, ['schema_version'], '1')],
        ['no season', changed(base, ['season'], REMOVE)],
        ['season two years', changed(base, ['season'], '2026-2028')],
        ['season short', changed(base, ['season'], '2026-27')],
        ['season full-width', changed(base, ['season'], trapped('2026-2027')[0])],
        ['since before July', changed(base, ['since'], '2026-06-30')],
        ['since on July 1', changed(base, ['since'], '2026-07-01')],
        ['since Feb 30', changed(base, ['since'], '2027-02-30')],
        ['since after through', changed(base, ['since'], '2027-01-13')],
        ['through after June', changed(base, ['through'], '2027-07-01')],
        ['through with a newline', changed(base, ['through'], '2027-01-12\n')],
        ['digest upper case', changed(base, ['content_sha256'], '5'.repeat(63) + 'A')],
        ['digest short', changed(base, ['content_sha256'], '5'.repeat(63))],
        ['digest null with rows', changed(base, ['content_sha256'], null)],
        ['emptied', made(base, (file) => {
          file.content_sha256 = null;
          for (const key of ['gaps', 'closed', 'delayed', 'remote', 'early_dismissal']) file[key] = [];
        })],
        ['gap negative', changed(base, ['gaps', 1], -1)],
        ['gap not whole', changed(base, ['gaps', 1], 1.5)],
        ['gap true', changed(base, ['gaps', 0], true)],
        ['gap past the directory', changed(base, ['gaps', 2], 3)],
        ['closed column short', changed(base, ['closed', 2], REMOVE)],
        ['no remote column', changed(base, ['remote'], REMOVE)],
        ['a row of no days', made(base, (file) => {
          file.closed[0] = 0;
          file.delayed[0] = 0;
        })],
        ['a row past its span', changed(base, ['closed', 0], 79)],
        ['a row at its span', made(base, (file) => {
          file.closed[0] = 78;
          file.delayed[0] = 0;
        })],
        ['a count of 367', changed(base, ['remote', 2], 367)],
        ['a count as text', changed(base, ['closed', 0], '2')],
        ['directory schools not whole', changed(base, ['directory', 'schools'], 6.5)],
        ['directory day bad', changed(base, ['directory', 'generated_on'], '2026-9-24')],
        ['no directory', changed(base, ['directory'], REMOVE)],
        ['an unknown key', changed(base, ['note'], 'x')],
      ];
      for (const [name, json] of mutations) cases.push(['file', name, null, json, parseSeason(copyOf(json)) !== null]);
      const file = parseSeason(copyOf(base));
      const own = base.directory;
      const other = { ...own, generated_on: '2026-09-25' };
      const nows = [
        '2027-01-12T12:00:00Z',
        '2027-01-13T12:00:00Z',
        '2027-01-14T07:59:59Z',
        '2027-01-14T08:00:00Z',
        '2027-01-14T08:59:59Z',
        '2027-01-14T09:00:00Z',
        '2027-01-14T09:00:01Z',
        '2027-01-14T10:00:00Z',
        '2027-01-15T09:00:00Z',
        '2026-12-01T00:00:00Z',
        '2026-10-01T00:00:00Z',
      ].map((text) => Date.parse(text));
      nows.push(NaN);
      for (const directory of [own, other]) {
        for (let school = 0; school <= own.schools; school += 1) {
          for (const now of nows) {
            const found = answer(() => schoolSeason(file, school, directory, new Date(now)));
            const shown = found === null || found === THROWS ? found : [found.days.closed, found.days.delayed, found.days.remote, found.days.earlyDismissal, found.since];
            cases.push(['school', school, directory, num(now), shown]);
          }
        }
      }
      for (let hour = 0; hour < 24; hour += 1) {
        const now = Date.parse('2027-01-12T00:00:00Z') + hour * HOUR_MS;
        cases.push(['lastDayOver', now, answer(() => lastDayOver(new Date(now)))]);
      }
      return cases;
    },
  },
  {
    // [now, zone, mapDay, nextMapTurn, localDay, todayEverywhere, clockToday, schoolToday, narrower]
    // (all of now and zone; nextMapTurn an instant). `narrower` is true where the site accepted a
    // zone name that is not on the app's list: there the app must answer as for a zone it cannot
    // read. Every 30 minutes over W3 in each zone of Z10, every minute within 2 minutes of each
    // 3:30 PM, midnight and 7:30 AM there and of each clock change, then each odd name at 6
    // instants.
    family: 'map-day',
    minCases: 5000,
    modules: ['data/map-day.ts', 'data/school-day.ts'],
    cases: (site, context) => {
      const mapDay = site['data/map-day.ts'];
      const { schoolToday } = site['data/school-day.ts'];
      const one = (now, zone) => {
        const date = new Date(now);
        return [
          num(now),
          zone,
          answer(() => mapDay.mapDay(date, zone)),
          answer(() => {
            const turn = mapDay.nextMapTurn(date, zone);
            return turn === null ? null : ms(turn);
          }),
          answer(() => mapDay.localDay(date, zone)),
          answer(() => mapDay.todayEverywhere(date)),
          answer(() => mapDay.clockToday(date, zone)),
          answer(() => schoolToday(date, zone)),
          narrowerZone(zone, context.onList, mapDay),
        ];
      };
      const CONTIGUOUS = Z8.slice(0, 5);
      const cases = [];
      for (const zone of Z10) {
        const instants = new Set();
        for (const start of W3) {
          for (let at = start; at < start + WINDOW_MS; at += 30 * MINUTE_MS) instants.add(at);
          const near = (at) => {
            for (let k = -2; k <= 2; k += 1) {
              const t = at + k * MINUTE_MS;
              if (t >= start && t < start + WINDOW_MS) instants.add(t);
            }
          };
          const clocks = zone === null ? [] : zone === '*' ? CONTIGUOUS : zone === '?' ? [] : [zone];
          for (const clock of clocks) {
            for (let day = addDays(new Date(start).toISOString().slice(0, 10), -1); day <= addDays(new Date(start).toISOString().slice(0, 10), 3); day = addDays(day, 1)) {
              for (const minute of [0, 7 * 60 + 30, 15 * 60 + 30]) near(atLocal(day, minute, clock));
            }
            // Each clock change: the first minute whose offset differs from the minute before.
            for (let at = start; at < start + WINDOW_MS; at += MINUTE_MS) {
              if (wallMs(at, clock) - at !== wallMs(at - MINUTE_MS, clock) - (at - MINUTE_MS)) near(at);
            }
          }
          if (zone === null || zone === '*') {
            // The hours the day that is today everywhere begins and ends: 04:00 and 08:00 UTC.
            for (let day = start; day < start + WINDOW_MS; day += DAY_MS) {
              near(day + 4 * HOUR_MS);
              near(day + 8 * HOUR_MS);
            }
          }
        }
        for (const at of [...instants].sort((a, b) => a - b)) cases.push(one(at, zone));
      }
      const odd = ['2026-11-01T05:59:00Z', '2026-11-01T06:01:00Z', '2027-01-12T21:29:00Z', '2027-01-12T21:31:00Z', '2027-03-14T07:59:00Z', '2027-03-14T08:01:00Z'].map((text) => Date.parse(text));
      for (const zone of ZX) for (const at of odd) cases.push(one(at, zone));
      cases.push(one(NaN, 'America/Chicago'), one(NaN, null), one(NaN, '*'));
      return cases;
    },
  },
  {
    // [name, isTimeZone(name), regionOf(name), on the app's list]: every name on the list, then
    // every odd name.
    family: 'zones',
    minCases: 440,
    modules: ['data/map-day.ts'],
    cases: (site, context) => {
      const { isTimeZone, regionOf } = site['data/map-day.ts'];
      return [...context.zoneNames, ...ZX].map((name) => [name, isTimeZone(name), regionOf(name), context.onList.has(name)]);
    },
  },
  {
    // ["file", name, path, json, parseClosings accepts, rows]: the three copied closings files
    //   (path, json null) and one-change mutations of the first (path null, json the file); the
    //   "status" cases are of the three copies and of the mutation "three days". For a
    //   file the site accepts, rows holds, for each of its days in order, [day, [rowOn(file, day,
    //   school) for each school 0 ... schools]] (one past the end included); else null.
    // ["status", name, directory, school, zone, now, schoolStatus, litStatus]: the site's
    //   schoolStatus({school, directory, closings, covered: null, now, timeZone: zone}) as
    //   [today, tomorrow, later] (later: [[day, row]...], empty for none), and
    //   litStatus(closings, directory, school, zone, now). `directory` is null for the file's
    //   own directory stamp, else the stamp given.
    // A row is [status, reason, announcedAt, shiftMinutes, clockMinute, manual, details].
    family: 'closings',
    minCases: 3000,
    modules: ['data/closings.ts', 'data/school-day.ts'],
    cases: (site) => {
      const { parseClosings, litStatus } = site['data/closings.ts'];
      const { rowOn, schoolStatus } = site['data/school-day.ts'];
      const rowsOf = (file) => {
        if (file === null) return null;
        return file.days.map((group) => {
          const rows = [];
          for (let school = 0; school <= file.directory.schools; school += 1) rows.push(rowCase(rowOn(file, group.day, school)));
          return [group.day, rows];
        });
      };
      const sources = [
        ['examples', 'schemas/examples/synthetic-closings.json'],
        ['live', 'live/golden/synthetic_closings.json'],
        ['manual', 'live/golden/synthetic_manual_closings.json'],
      ];
      const cases = [];
      const files = [];
      for (const [name, path] of sources) {
        const file = parseClosings(fixture(path));
        cases.push(['file', name, path, null, file !== null, rowsOf(file)]);
        if (file !== null) files.push([name, file]);
      }
      const base = fixture(sources[0][1]);
      const day2 = (file) => file.days[1];
      const mutations = [
        ['schema 2', changed(base, ['schema_version'], 2)],
        ['schema as text', changed(base, ['schema_version'], '1')],
        ['generated_at without Z', changed(base, ['generated_at'], '2027-01-12T13:05:00')],
        ['generated_at Feb 30', changed(base, ['generated_at'], '2027-02-30T13:05:00Z')],
        ['no directory', changed(base, ['directory'], REMOVE)],
        ['stamp day short', changed(base, ['directory', 'generated_on'], '2026-9-24')],
        ['stamp day full-width', changed(base, ['directory', 'generated_on'], trapped('2026-09-24')[0])],
        ['stamp day with a newline', changed(base, ['directory', 'generated_on'], trapped('2026-09-24')[2])],
        ['stamp schools not whole', changed(base, ['directory', 'schools'], 1.5)],
        ['stamp schools negative', changed(base, ['directory', 'schools'], -1)],
        ['stamp districts as text', changed(base, ['directory', 'districts'], '2')],
        ['days not a list', changed(base, ['days'], {})],
        ['no days', changed(base, ['days'], [])],
        ['three days', made(base, (file) => file.days.push({ ...copyOf(day2(file)), day: '2027-01-14' }))],
        ['four days', made(base, (file) => {
          file.days.push({ ...copyOf(day2(file)), day: '2027-01-14' });
          file.days.push({ ...copyOf(day2(file)), day: '2027-01-15' });
        })],
        ['days unsorted', made(base, (file) => file.days.reverse())],
        ['a day twice', made(base, (file) => { file.days[1].day = file.days[0].day; })],
        ['a day short', changed(base, ['days', 0, 'day'], '2027-1-12')],
        ['a day full-width', changed(base, ['days', 0, 'day'], trapped('2027-01-12')[0])],
        ['no gaps column', changed(base, ['days', 0, 'gaps'], REMOVE)],
        ['no announced column', changed(base, ['days', 0, 'announced'], REMOVE)],
        ['no shifts column', changed(base, ['days', 1, 'shifts'], REMOVE)],
        ['a day of no rows', made(base, (file) => {
          for (const key of ['gaps', 'statuses', 'announced', 'reasons']) file.days[1][key] = [];
          file.days[1].manual = [];
        })],
        ['status 4', changed(base, ['days', 0, 'statuses', 0], 4)],
        ['status negative', changed(base, ['days', 0, 'statuses', 0], -1)],
        ['status not whole', changed(base, ['days', 0, 'statuses', 0], 0.5)],
        ['status true', changed(base, ['days', 0, 'statuses', 0], true)],
        ['a gap not whole', changed(base, ['days', 0, 'gaps', 1], 1.5)],
        ['a gap negative', changed(base, ['days', 0, 'gaps', 1], -1)],
        ['a gap true', changed(base, ['days', 0, 'gaps', 0], true)],
        ['announced at the limit', changed(base, ['days', 0, 'announced', 0], 20160)],
        ['announced past the limit', changed(base, ['days', 0, 'announced', 0], 20161)],
        ['a reason past the names', changed(base, ['days', 0, 'reasons', 0], 99)],
        ['a reason negative', changed(base, ['days', 0, 'reasons', 0], -1)],
        ['a reason true', changed(base, ['days', 0, 'reasons', 0], true)],
        ['a shift for a closed row', made(base, (file) => file.days[1].shifts.push(60))],
        ['a shift of 0', changed(base, ['days', 0, 'shifts', 0], 0)],
        ['a shift of 720', changed(base, ['days', 0, 'shifts', 0], 720)],
        ['a shift of 721', changed(base, ['days', 0, 'shifts', 0], 721)],
        ['a clock of 1439', changed(base, ['days', 0, 'clocks', 0], 1439)],
        ['a clock of 1440', changed(base, ['days', 0, 'clocks', 0], 1440)],
        ['statuses longer', made(base, (file) => file.days[0].statuses.push(0))],
        ['no manual column', changed(base, ['days', 1, 'manual'], REMOVE)],
        ['manual unsorted', changed(base, ['days', 0, 'manual'], [1, 0])],
        ['manual past the rows', changed(base, ['days', 0, 'manual'], [5])],
        ['manual twice', changed(base, ['days', 0, 'manual'], [0, 0])],
        ['manual as text', changed(base, ['days', 0, 'manual'], ['0'])],
        ['manual set', changed(base, ['days', 0, 'manual'], [1, 4])],
        ['details as text', changed(base, ['days', 0, 'details'], 'x')],
        ['details read', changed(base, ['days', 0, 'details'], [[0, [1, 4]], [3, [0, 21]]])],
        ['details code 22', changed(base, ['days', 0, 'details'], [[0, [22]]])],
        ['details codes unsorted', changed(base, ['days', 0, 'details'], [[0, [3, 1]]])],
        ['details rows unsorted', changed(base, ['days', 0, 'details'], [[1, [2]], [0, [1]]])],
        ['details no codes', changed(base, ['days', 0, 'details'], [[0, []]])],
        ['details a pair of three', changed(base, ['days', 0, 'details'], [[0, [1], 2]])],
        ['no details column', changed(base, ['days', 0, 'details'], REMOVE)],
        ['an unknown key', changed(base, ['note'], 'x')],
      ];
      for (const [name, json] of mutations) {
        const file = parseClosings(copyOf(json));
        cases.push(['file', name, null, json, file !== null, rowsOf(file)]);
        // A file of three days also has rows after tomorrow: schoolStatus's later rows.
        if (file !== null && name === 'three days') files.push([name, file]);
      }
      // Across the files' days: 4 or more before 3:30 PM and 4 or more after it on every US clock.
      const offsets = [9, 12, 15, 19, 20.5, 21.5, 22.5, 23.5, 26, 28, 30, 33, 36, 40].map((hours) => hours * HOUR_MS);
      for (const [name, file] of files) {
        const first = Date.parse(`${file.days[0].day}T00:00:00Z`);
        const others = [null, { ...file.directory, generated_on: addDays(file.directory.generated_on, 1) }];
        for (const directory of others) {
          const stamp = directory ?? file.directory;
          const zones = directory === null ? Z10 : ['America/Chicago'];
          const times = directory === null ? offsets : offsets.slice(0, 3);
          for (let school = 0; school <= file.directory.schools; school += 1) {
            for (const zone of zones) {
              for (const offset of times) {
                const now = new Date(first + offset);
                const status = answer(() => schoolStatus({ school, directory: stamp, closings: file, covered: null, now, timeZone: zone }));
                const shown =
                  status === THROWS
                    ? status
                    : [
                        status.today === 'open' ? 'open' : rowCase(status.today),
                        rowCase(status.tomorrow),
                        (status.later ?? []).map((later) => [later.day, rowCase(later.row)]),
                      ];
                cases.push(['status', name, directory, school, zone, ms(now), shown, answer(() => litStatus(file, stamp, school, zone, now))]);
              }
            }
          }
        }
      }
      return cases;
    },
  },
  {
    // ["file", name, path, json, parsePredictions accepts, narrower, zones]: the two copied
    //   predictions files (path, json null), mutations of them (path null, json the file), one
    //   for each odd zone name in a district's time_zone and one in the private schools' zones.
    //   zones, for a file the site accepts: [[zoneOf(z, -1, d) for d in 0 ... districts],
    //   [zoneOf(z, s, -1) for s in 0 ... schools]] with z = zonesOf(file) (one past the end of
    //   each included); else null. `narrower` is true where the site accepted the file and one of
    //   its zones is not on the app's list: there the app must refuse the file.
    // ["outlook", name, directory, shipped, district, school, now, outlook, headline]: the site's
    //   schoolOutlook({district, school, directory, shipped, predictions, now}) as [timeZone,
    //   today, tomorrow], each day as ["forecast", noSchool, delay, day, busesAt] or
    //   ["no_threat"]; then headlineDay(outlook, decided, now)'s day for decided {today, tomorrow}
    //   = [false, false], [true, false], [false, true], [true, true]. `directory` is null for
    //   the file's own stamp.
    // ["underWay", day, now, zone, buses, underWay(day, now, zone, buses)]
    family: 'predictions',
    minCases: 1500,
    modules: ['data/map-day.ts', 'data/school-day.ts', 'app/chance.ts'],
    cases: (site, context) => {
      const mapDay = site['data/map-day.ts'];
      const { parsePredictions, zonesOf, zoneOf } = mapDay;
      const { schoolOutlook } = site['data/school-day.ts'];
      const { headlineDay, underWay } = site['app/chance.ts'];
      const sources = [
        ['examples', 'schemas/examples/synthetic-predictions.json'],
        ['golden', 'predict/golden/synthetic_predictions.json'],
      ];
      const zonesCase = (file) => {
        if (file === null) return null;
        const zones = zonesOf(file);
        const districts = [];
        for (let d = 0; d <= file.directory.districts; d += 1) districts.push(zoneOf(zones, -1, d));
        const schools = [];
        for (let s = 0; s <= file.directory.schools; s += 1) schools.push(zoneOf(zones, s, -1));
        return [districts, schools];
      };
      const narrower = (file) =>
        file !== null &&
        [...file.districts.map((entry) => entry.time_zone), ...(file.zones ?? [])].some((zone) => narrowerZone(zone, context.onList, mapDay));
      const cases = [];
      const usable = [];
      const addFile = (name, path, json) => {
        const file = parsePredictions(copyOf(json));
        cases.push(['file', name, path, path === null ? json : null, file !== null, narrower(file), zonesCase(file)]);
        return file;
      };
      const bases = sources.map(([name, path]) => {
        const json = fixture(path);
        const file = addFile(name, path, json);
        if (file !== null) usable.push([name, file]);
        return json;
      });
      const [one, two] = bases;
      const mutations = [
        ['schema 2', changed(one, ['schema_version'], 2)],
        ['generated_at without Z', changed(one, ['generated_at'], '2027-01-12T11:00:00')],
        ['no directory', changed(one, ['directory'], REMOVE)],
        ['stamp schools not whole', changed(one, ['directory', 'schools'], 6.5)],
        ['no days', changed(one, ['days'], [])],
        ['days apart', changed(one, ['days', 1], '2027-01-14')],
        ['days backwards', made(one, (file) => file.days.reverse())],
        ['a day full-width', changed(one, ['days', 0], trapped('2027-01-12')[0])],
        ['districts not a list', changed(one, ['districts'], {})],
        ['a district not whole', changed(one, ['districts', 0, 'district'], 0.5)],
        ['a district short a day', changed(one, ['districts', 0, 'days', 1], REMOVE)],
        ['no time_zone', changed(one, ['districts', 0, 'time_zone'], REMOVE)],
        ['a state unknown', changed(one, ['districts', 0, 'days', 0, 'state'], 'storm')],
        ['a chance of 0', changed(one, ['districts', 0, 'days', 0, 'p_no_school'], 0)],
        ['a chance of 0.01', changed(one, ['districts', 0, 'days', 0, 'p_no_school'], 0.01)],
        ['a chance of 0.99', changed(one, ['districts', 0, 'days', 0, 'p_no_school'], 0.99)],
        ['a chance of 0.995', changed(one, ['districts', 0, 'days', 0, 'p_no_school'], 0.995)],
        ['a chance as text', changed(one, ['districts', 0, 'days', 0, 'p_no_school'], '0.62')],
        ['a delay above 1', changed(one, ['districts', 0, 'days', 0, 'p_delay'], 1.01)],
        ['a delay of 0', changed(one, ['districts', 0, 'days', 0, 'p_delay'], 0)],
        ['no reasons', changed(one, ['districts', 0, 'days', 0, 'reasons'], REMOVE)],
        ['a reason of 8', changed(one, ['districts', 0, 'days', 0, 'reasons', 0], 8)],
        ['a reason of 7', changed(one, ['districts', 0, 'days', 0, 'reasons', 0], 7)],
        ['a reason true', changed(one, ['districts', 0, 'days', 0, 'reasons', 0], true)],
        ['buses on another day', changed(one, ['districts', 0, 'days', 0, 'buses_at'], '2027-01-13T13:00:00Z')],
        ['buses unreadable', changed(one, ['districts', 0, 'days', 0, 'buses_at'], '7 AM')],
        ['buses early', changed(one, ['districts', 0, 'days', 1, 'buses_at'], '2027-01-13T11:20:00Z')],
        ['schools unsorted', made(one, (file) => file.schools.reverse())],
        ['a school zone past the list', changed(one, ['schools', 0, 'zone'], 1)],
        ['a school short a day', changed(one, ['schools', 0, 'days', 1], REMOVE)],
        ['a school outlook past the list', changed(one, ['schools', 0, 'days', 0], 3)],
        ['an outlook unknown', changed(one, ['outlooks', 0, 'state'], 'storm')],
        ['no private schools', made(one, (file) => {
          delete file.schools;
          delete file.outlooks;
          delete file.zones;
        })],
        ['zones not a list', changed(one, ['zones'], 'America/Chicago')],
        ['late', changed(one, ['generated_at'], '2027-01-12T13:00:00Z')],
        ['golden late', changed(two, ['generated_at'], '2026-01-07T13:00:00Z')],
        ['golden district in Denver', changed(two, ['districts', 0, 'time_zone'], 'America/Denver')],
      ];
      for (const [name, json] of mutations) {
        const file = addFile(name, null, json);
        if (file !== null && (name === 'late' || name === 'golden late')) usable.push([name, file]);
      }
      for (const zone of ZX) {
        addFile(`district zone ${JSON.stringify(zone)}`, null, changed(one, ['districts', 1, 'time_zone'], zone));
        addFile(`school zone ${JSON.stringify(zone)}`, null, changed(one, ['zones', 0], zone));
      }
      const day = (value) => {
        if (value === null) return null;
        if (value.state === 'no_threat') return ['no_threat'];
        return ['forecast', value.noSchool, value.delay, value.day ?? null, ms(value.detail?.busesAt ?? null)];
      };
      const DECIDED = [
        { today: false, tomorrow: false },
        { today: true, tomorrow: false },
        { today: false, tomorrow: true },
        { today: true, tomorrow: true },
      ];
      for (const [name, file] of usable) {
        const generated = Date.parse(file.generated_at);
        const nows = [];
        for (let minutes = -20; minutes <= 100; minutes += 5) nows.push(generated + minutes * MINUTE_MS);
        const units = [];
        for (let d = 0; d <= file.directory.districts; d += 1) units.push([d, null]);
        for (let s = 0; s <= file.directory.schools; s += 1) units.push([null, s]);
        units.push([null, null]);
        const outlookCase = (directory, shipped, [district, school], now) => {
          const at = new Date(now);
          const outlook = answer(() =>
            schoolOutlook({ district, school, directory: directory ?? file.directory, shipped, predictions: file, now: at }),
          );
          const shown = outlook === null || outlook === THROWS ? outlook : [outlook.timeZone, day(outlook.today), day(outlook.tomorrow)];
          const headline =
            outlook === THROWS
              ? THROWS
              : DECIDED.map((decided) => answer(() => headlineDay(outlook, decided, at)?.day ?? null));
          return ['outlook', name, directory, shipped, district, school, now, shown, headline];
        };
        for (const unit of units) for (const now of nows) cases.push(outlookCase(null, true, unit, now));
        const other = { ...file.directory, generated_on: addDays(file.directory.generated_on, 1) };
        cases.push(outlookCase(other, true, [0, null], generated));
        cases.push(outlookCase(null, false, [0, null], generated));
      }
      // underWay: around 7:30 AM on each school day's clock, with no bus time, buses before
      // 7:30 and buses after it.
      const days = ['2026-01-06', '2026-01-07', '2027-01-12', '2027-01-13'];
      for (const zone of [...Z8.slice(0, 7), 'Mars/Olympus', 'america/chicago']) {
        for (const schoolDay of days) {
          const clock = zone === 'Mars/Olympus' || zone === 'america/chicago' ? 'America/Chicago' : zone;
          const busTimes = [null, atLocal(schoolDay, 6 * 60 + 45, clock), atLocal(schoolDay, 8 * 60, clock)];
          for (const minute of [6 * 60 + 44, 6 * 60 + 45, 7 * 60 + 29, 7 * 60 + 30, 7 * 60 + 31, 8 * 60, 23 * 60 + 59]) {
            const now = atLocal(schoolDay, minute, clock);
            for (const buses of busTimes) {
              cases.push(['underWay', schoolDay, now, zone, buses, answer(() => underWay(schoolDay, new Date(now), zone, buses === null ? null : new Date(buses)))]);
            }
          }
        }
      }
      return cases;
    },
  },
  {
    // [generatedAt, now, heldMs, online, zone, updateState(...)]: the answer [text, live] or null.
    family: 'freshness',
    minCases: 400,
    modules: ['state/freshness.ts'],
    cases: (site) => {
      const { updateState } = site['state/freshness.ts'];
      const generatedAt = '2027-01-12T13:05:00Z';
      const generated = Date.parse(generatedAt);
      const S = 1000;
      const M = MINUTE_MS;
      const ages = [-3 * M, -2 * M - S, -2 * M, -2 * M + S, -M, -S, 0, S, M, 2 * M - S, 2 * M, 2 * M + S, 10 * M, 20 * M - S, 20 * M, 20 * M + S, 21 * M, 59 * M, 2 * HOUR_MS, 11 * HOUR_MS, 23 * HOUR_MS, 25 * HOUR_MS];
      const cases = [];
      for (const zone of ['America/New_York', 'America/Denver', 'Pacific/Honolulu']) {
        for (const online of [true, false]) {
          for (const heldMs of [0, 19 * M, 20 * M, 21 * M]) {
            for (const age of ages) {
              const now = generated + age;
              const state = answer(() => updateState({ generatedAt, online, timeZone: zone, now: new Date(now), heldMs }));
              cases.push([generatedAt, now, heldMs, online, zone, state === null || state === THROWS ? state : [state.text, state.live]]);
            }
          }
        }
      }
      for (const bad of ['2027-02-30T13:05:00Z', '2027-01-12T13:05:00', '', trapped(generatedAt)[0]]) {
        const state = answer(() => updateState({ generatedAt: bad, online: true, timeZone: 'America/Chicago', now: new Date(generated), heldMs: 0 }));
        cases.push([bad, generated, 0, true, 'America/Chicago', state === null || state === THROWS ? state : [state.text, state.live]]);
      }
      return cases;
    },
  },
  {
    // [text, isSchoolId(text), parseSchoolId(text)]
    family: 'ids',
    minCases: 60,
    modules: ['state/ids.ts'],
    cases: (site) => {
      const { isSchoolId, parseSchoolId } = site['state/ids.ts'];
      const PUBLIC = '170993000713';
      const PRIVATE = 'A1B2C3D4';
      const plain = [
        PUBLIC,
        '010000500870',
        '000000000000',
        '999999999999',
        PRIVATE,
        '00000000',
        'ZZZZZZZZ',
        'K9100314',
        'a1b2c3d4',
        'k9100314',
        'A1b2C3d4',
        ` ${PUBLIC}`,
        `${PUBLIC} `,
        `  ${PRIVATE}  `,
        ` a1b2c3d4 `,
        '17099300071',
        '1709930007134',
        'A1B2C3D',
        'A1B2C3D45',
        'A1B2-C3D',
        'A1B2C3D!',
        '1709930 00713',
        '',
        ' ',
        '   ',
        '0',
        '12345',
        '1709930',
        '-17099300071',
        '+17099300071',
        '1.7099300071',
        '1e1099300071',
        'ÄÖÜ12345',
        'A1B2C3D4E5F6G7H8',
        'A1B2C3D4E5F6G7H8I',
        '170993000713170993000713',
        'null',
        'undefined',
        'ABCDEFGH',
        'abcdefgh',
      ];
      const traps = (id) => [
        ...trapped(id),
        ` ${id} `,
        `\t${id}\t`,
        `${' '.repeat(Math.floor((16 - id.length) / 2))}${id}${' '.repeat(Math.ceil((16 - id.length) / 2))}`,
        `${' '.repeat(Math.floor((17 - id.length) / 2))}${id}${' '.repeat(Math.ceil((17 - id.length) / 2))}`,
        `${id}${' '.repeat(17 - id.length - 2)}\u{1D7CE}`,
      ];
      const texts = [...plain, ...traps(PUBLIC), ...traps(PRIVATE), 'ß1b2c3d', 'ǅ1B2C3D4'];
      return texts.map((text) => [text, isSchoolId(text), parseSchoolId(text)]);
    },
  },
];

class Stop extends Error {
  /**
   * @param {number} code
   * @param {string} message
   */
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function say(line) {
  process.stdout.write(`${line}\n`);
}

/** A repository path with forward slashes, whatever the machine. */
function repoPath(absolute) {
  return relative(REPO, absolute).split(sep).join('/');
}

function nodeIsNewEnough() {
  const [major, minor] = process.versions.node.split('.').map((part) => Number(part));
  return major > 22 || (major === 22 && minor >= 18);
}

// Writing ------------------------------------------------------------------------------

/** A JSON string in ASCII: everything outside it is written as a \u escape. */
function quote(text) {
  return JSON.stringify(text).replace(
    /[\u007f-\uffff]/g,
    (unit) => `\\u${unit.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
}

/**
 * One value as JSON on one line, with sorted keys. Refuses what JSON cannot hold: a
 * golden answer is null, true, false, a finite number, a string, a list or a plain object.
 * @param {unknown} value
 * @param {string} where
 * @returns {string}
 */
function canonical(value, where) {
  if (value === null) return 'null';
  if (typeof value === 'string') return quote(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Stop(EXIT_CANNOT_LOAD, `${where} is ${value}, which JSON cannot hold`);
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, index) => canonical(item, `${where}[${index}]`)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const kind = Object.getPrototypeOf(value);
    if (kind !== Object.prototype && kind !== null) {
      throw new Stop(EXIT_CANNOT_LOAD, `${where} is not a plain object`);
    }
    const keys = Object.keys(value).sort();
    return `{${keys.map((key) => `${quote(key)}:${canonical(value[key], `${where}.${key}`)}`).join(',')}}`;
  }
  throw new Stop(EXIT_CANNOT_LOAD, `${where} is a ${typeof value}, which a golden file cannot hold`);
}

/** The whole text of a golden file. */
function fileText(made) {
  const lines = [`{"family": ${quote(made.family)}, "min_cases": ${made.minCases}, "made_from": [`];
  made.madeFrom.forEach((source, index) => {
    const comma = index < made.madeFrom.length - 1 ? ',' : '';
    lines.push(`{"path": ${quote(source.path)}, "sha256": ${quote(source.sha256)}}${comma}`);
  });
  lines.push('], "cases": [');
  made.caseLines.forEach((line, index) => {
    lines.push(line + (index < made.caseLines.length - 1 ? ',' : ''));
  });
  lines.push(']}');
  return `${lines.join('\n')}\n`;
}

// Loading the site's code ----------------------------------------------------------------

/**
 * Loads the site's modules and runs every family.
 * @returns {Promise<Array<{ family: string, minCases: number, madeFrom: Array<{ path: string, sha256: string }>, caseLines: string[] }>>}
 */
async function makeAll() {
  const { reported, siteRoot } = await import('./node-register.mjs');
  /** @type {Map<string, Set<string>>} which site file imports which */
  const imports = new Map();
  /** @type {Set<string>} */
  const loaded = new Set();
  const takeReports = () => {
    for (const message of reported()) {
      if (message.kind === 'load') loaded.add(message.path);
      if (message.kind === 'import') {
        if (!imports.has(message.from)) imports.set(message.from, new Set());
        imports.get(message.from).add(message.to);
      }
    }
  };

  // The zone list comes first: two families mark the zone names the site accepts and the
  // list does not hold.
  const mapDayFile = join(siteRoot, 'data', 'map-day.ts');
  let zoneNames;
  try {
    zoneNames = zoneList(await import(pathToFileURL(mapDayFile).href));
  } catch (error) {
    if (error instanceof Stop) throw error;
    takeReports();
    throw new Stop(EXIT_CANNOT_LOAD, `${repoPath(mapDayFile)}: ${error instanceof Error ? error.message : String(error)}`);
  }
  const context = { zoneNames, onList: new Set(zoneNames) };

  const made = [];
  for (const spec of FAMILIES) {
    /** @type {Record<string, unknown>} */
    const site = {};
    for (const name of spec.modules) {
      const file = join(siteRoot, ...name.split('/'));
      try {
        site[name] = await import(pathToFileURL(file).href);
      } catch (error) {
        takeReports();
        throw new Stop(EXIT_CANNOT_LOAD, `${repoPath(file)}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    takeReports();

    let cases;
    try {
      cases = spec.cases(site, context);
    } catch (error) {
      if (error instanceof Stop) throw error;
      throw new Stop(
        EXIT_CANNOT_LOAD,
        `the family '${spec.family}' could not be run: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    const caseLines = cases.map((one, index) => canonical(one, `${spec.family} case ${index}`));

    // Every site file this family's modules pulled in, found by following the imports.
    const files = new Set();
    const queue = spec.modules.map((name) => join(siteRoot, ...name.split('/')));
    while (queue.length > 0) {
      const file = queue.pop();
      if (files.has(file)) continue;
      files.add(file);
      for (const next of imports.get(file) ?? []) queue.push(next);
    }
    const madeFrom = [...files]
      .map((file) => ({
        path: repoPath(file),
        sha256: createHash('sha256').update(readFileSync(file)).digest('hex'),
      }))
      .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));

    made.push({ family: spec.family, minCases: spec.minCases, madeFrom, caseLines });
  }

  // Nothing may have been loaded from outside what the words watch covers.
  const outside = [...loaded]
    .map(repoPath)
    .filter((path) => !path.startsWith(WATCHED_FOLDER) && !WATCHED_FILES.includes(path))
    .sort();
  if (outside.length > 0) {
    throw new Stop(
      EXIT_OUTSIDE_WATCH,
      `loaded from outside ${WATCHED_FOLDER} and ${WATCHED_FILES.join(', ')}, which the words watch does not cover:\n  ${outside.join('\n  ')}`,
    );
  }
  return { made, zoneNames };
}

/** The text of ZoneNames.swift. */
function zoneNamesText(names) {
  const lines = [
    '// ZoneNames.swift: written by ios/tools/gen-golden.mjs. Generated: do not edit.',
    '//',
    "// The time zone names the app accepts (item 27 of the M0 spec). A name is a time zone only",
    "// if it is on this list, letter for letter, and this machine's Foundation knows it. The",
    "// candidates are Node's own zone names, UTC and the long US spellings Node leaves out; each",
    "// is kept only if the site's isTimeZone accepts it (web/src/data/map-day.ts), so the list is",
    "// never wider than the site. `gen-golden.mjs --check` compares this file whole.",
    '',
    'enum ZoneNames {',
    '    static let all: Set<String> = [',
    ...names.map((name) => `        ${quote(name)},`),
    '    ]',
    '}',
  ];
  return `${lines.join('\n')}\n`;
}

// Checking -------------------------------------------------------------------------------

function shorten(text) {
  return text.length <= 300 ? text : `${text.slice(0, 300)}... (${text.length} characters)`;
}

/**
 * Where two JSON values first differ, as a path and the two values there; null when
 * they are the same.
 * @param {unknown} committed
 * @param {unknown} now
 * @param {string} path
 * @returns {{ path: string, committed: string, now: string } | null}
 */
function firstDifference(committed, now, path) {
  const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
  if (Array.isArray(committed) && Array.isArray(now)) {
    for (let index = 0; index < Math.max(committed.length, now.length); index += 1) {
      const found = firstDifference(committed[index], now[index], `${path}[${index}]`);
      if (found !== null) return found;
    }
    return null;
  }
  if (isObject(committed) && isObject(now)) {
    for (const key of [...new Set([...Object.keys(committed), ...Object.keys(now)])].sort()) {
      const found = firstDifference(committed[key], now[key], path === '' ? key : `${path}.${key}`);
      if (found !== null) return found;
    }
    return null;
  }
  if (committed === now) return null;
  const show = (value) => (value === undefined ? '(nothing)' : shorten(JSON.stringify(value)));
  return { path: path === '' ? '(the whole case)' : path, committed: show(committed), now: show(now) };
}

/**
 * Compares what was made with what is committed. Prints what differs.
 * @returns {boolean} true when every answer matches
 */
function check(made) {
  let same = true;
  const wanted = new Set(made.map((one) => `${one.family}.json`));
  const present = existsSync(GOLDEN) ? readdirSync(GOLDEN).filter((name) => name.endsWith('.json')) : [];
  for (const name of present.sort()) {
    if (!wanted.has(name)) {
      say(`differs: golden/${name} is committed, and no family makes it`);
      same = false;
    }
  }

  for (const one of made) {
    const path = join(GOLDEN, `${one.family}.json`);
    if (!existsSync(path)) {
      say(`differs: ${one.family}: golden/${one.family}.json is not committed`);
      same = false;
      continue;
    }
    let committed;
    try {
      committed = JSON.parse(readFileSync(path, 'utf8'));
    } catch (error) {
      say(`differs: ${one.family}: the committed file does not parse (${error instanceof Error ? error.message : error})`);
      same = false;
      continue;
    }
    const committedSources = new Map(
      (Array.isArray(committed.made_from) ? committed.made_from : []).map((source) => [source.path, source.sha256]),
    );
    const changedSources = [];
    for (const source of one.madeFrom) {
      if (!committedSources.has(source.path)) changedSources.push(`${source.path} (now loaded)`);
      else if (committedSources.get(source.path) !== source.sha256) changedSources.push(source.path);
    }
    for (const path of committedSources.keys()) {
      if (!one.madeFrom.some((source) => source.path === path)) changedSources.push(`${path} (no longer loaded)`);
    }

    const problems = [];
    if (committed.family !== one.family) problems.push(`the file says family '${committed.family}'`);
    if (committed.min_cases !== one.minCases) {
      problems.push(`min_cases is ${committed.min_cases} in the file and ${one.minCases} in the generator`);
    }
    const committedCases = Array.isArray(committed.cases) ? committed.cases : [];
    const committedLines = committedCases.map((value, index) => canonical(value, `${one.family} committed case ${index}`));
    const most = Math.max(committedLines.length, one.caseLines.length);
    for (let index = 0; index < most; index += 1) {
      if (committedLines[index] !== one.caseLines[index]) {
        const where =
          committedLines[index] === undefined || one.caseLines[index] === undefined
            ? null
            : firstDifference(committedCases[index], JSON.parse(one.caseLines[index]), '');
        problems.push(
          where === null
            ? `case ${index} is the first that differs\n    committed: ${shorten(committedLines[index] ?? '(no such case)')}\n    the site now: ${shorten(one.caseLines[index] ?? '(no such case)')}`
            : `case ${index} is the first that differs, at ${where.path}\n    committed: ${where.committed}\n    the site now: ${where.now}`,
        );
        break;
      }
    }

    if (problems.length > 0) {
      same = false;
      say(`differs: ${one.family}: ${problems.join('; ')}`);
      if (changedSources.length > 0) {
        say(`  site files changed since this golden file was made:\n    ${changedSources.join('\n    ')}`);
      } else {
        say('  no site file this family loads has changed since the golden file was made');
      }
    } else {
      for (const path of changedSources) say(`note: ${path} changed, no answer changed`);
    }
  }
  return same;
}

// Main -----------------------------------------------------------------------------------

async function main(argv) {
  if (!nodeIsNewEnough()) {
    throw new Stop(EXIT_USAGE, `this needs Node 22.18 or newer to load the site's TypeScript; this is ${process.versions.node}`);
  }
  if (argv.length > 1 || (argv.length === 1 && argv[0] !== '--check')) {
    throw new Stop(EXIT_USAGE, 'usage: node ios/tools/gen-golden.mjs [--check]');
  }
  const checking = argv[0] === '--check';

  const started = Date.now();
  const { made, zoneNames } = await makeAll();
  const zoneText = zoneNamesText(zoneNames);
  say(`zones: ${zoneNames.length} names on the list`);
  for (const one of made) {
    say(`${one.family}: ${one.caseLines.length} cases`);
    if (one.caseLines.length < one.minCases) {
      throw new Stop(EXIT_DIFFERS, `the family '${one.family}' has ${one.caseLines.length} cases, below its minimum of ${one.minCases}`);
    }
  }

  if (checking) {
    const zonesSame = existsSync(ZONE_NAMES) && readFileSync(ZONE_NAMES, 'utf8') === zoneText;
    if (!zonesSame) say(`differs: ${repoPath(ZONE_NAMES)} is not the zone list the site's code gives now`);
    if (!check(made) || !zonesSame) {
      throw new Stop(
        EXIT_DIFFERS,
        "an answer of the site's code differs from the committed golden files. Make them again (node ios/tools/gen-golden.mjs) and update the Swift port",
      );
    }
    say(`golden: ${made.length} ${made.length === 1 ? 'family matches' : 'families match'} the site's code, and the zone list (zone ${process.env.TZ}, ${Date.now() - started} ms)`);
    return;
  }

  mkdirSync(GOLDEN, { recursive: true });
  const stale = readdirSync(GOLDEN).filter(
    (name) => name.endsWith('.json') && !made.some((one) => `${one.family}.json` === name),
  );
  if (stale.length > 0) {
    throw new Stop(EXIT_DIFFERS, `no family makes these files in golden/: ${stale.join(', ')}. Remove them`);
  }
  for (const one of made) writeFileSync(join(GOLDEN, `${one.family}.json`), fileText(one));
  mkdirSync(dirname(ZONE_NAMES), { recursive: true });
  writeFileSync(ZONE_NAMES, zoneText);
  say(`golden: wrote ${made.length} ${made.length === 1 ? 'file' : 'files'} and the zone list (zone ${process.env.TZ}, ${Date.now() - started} ms)`);
}

try {
  await main(process.argv.slice(2));
} catch (error) {
  if (error instanceof Stop) {
    if (error.code === EXIT_CANNOT_LOAD) say("could not load the site's code");
    say(`gen-golden: ${error.message}`);
    process.exitCode = error.code;
  } else {
    // Anything unforeseen is a fault of this script or of the site's code under it, never
    // a changed word: it gets the loader's exit code, not the words message.
    say("could not load the site's code");
    say(`gen-golden: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}`);
    process.exitCode = EXIT_CANNOT_LOAD;
  }
}

import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';

import { copy, mapLocale, REASON_KEYS, shellFormat, STATUS_KEYS } from './copy';
import type { AlertLevelKey, HazardKey, StatusKey } from './copy';
import { chanceCopy, chanceFormat } from './copy-chance';
import type { BaseInput, ReasonInput, Zones } from './copy-chance';
import { format } from './copy-format';

// The house-style rules and the lint live in scripts/check-copy.mjs, a plain
// Node module; this is the slice of it the tests use.
interface Finding {
  file: string;
  line: number;
  column: number;
  message: string;
}
interface CheckCopy {
  problems: (text: string) => string[];
  copyLeaves: (node: unknown) => [string, string][];
  scanIndexHtml: (html: string, copyTree: unknown, file: string) => Promise<Finding[]>;
  scanManifest: (json: string, file: string, copyTree: unknown) => Finding[];
  lintProject: (options: {
    root: string;
    dist?: string;
  }) => Promise<{ findings: Finding[]; scanned: Record<string, number> }>;
}

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const REPO_ROOT = path.resolve(WEB_ROOT, '..');
const checkCopyModule = path.join(WEB_ROOT, 'scripts', 'check-copy.mjs');
const { problems, copyLeaves, scanIndexHtml, scanManifest, lintProject } = (await import(
  /* @vite-ignore */ checkCopyModule
)) as CheckCopy;

const NBSP = '\u00a0';
const strings = copyLeaves(copy);

/** Every problem in a list of strings, as "text: problem" lines, for one readable failure. */
function allProblems(texts: Iterable<string | null>): string[] {
  const found: string[] = [];
  for (const text of new Set(texts)) {
    if (text === null) continue;
    for (const problem of problems(text)) found.push(`${JSON.stringify(text)}: ${problem}`);
  }
  return found;
}

/** Every calendar day from `first` for `days` days, as YYYY-MM-DD. */
function calendarDays(first: string, days: number): string[] {
  const start = Date.parse(`${first}T00:00:00Z`);
  return Array.from({ length: days }, (_, i) =>
    new Date(start + i * 86_400_000).toISOString().slice(0, 10),
  );
}

/** Instants every `stepMinutes` through one year, so every hour, minute band and DST switch shows up. */
function instantsThrough(year: number, stepMinutes: number): Date[] {
  const start = Date.UTC(year, 0, 1);
  const end = Date.UTC(year + 1, 0, 1);
  const instants: Date[] = [];
  for (let t = start; t < end; t += stepMinutes * 60_000) instants.push(new Date(t));
  return instants;
}

const ZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'UTC',
];
const COUNTS = [0, 1, 2, 9, 10, 99, 100, 999, 1000, 1284, 9999, 10_000, 30_000, 131_072, 1_000_000];

describe('copy', () => {
  it('is one frozen tree of non-empty strings', () => {
    const pending: unknown[] = [copy];
    while (pending.length > 0) {
      const node = pending.pop();
      expect(Object.isFrozen(node)).toBe(true);
      for (const value of Object.values(node as object)) {
        if (typeof value === 'string') expect(value.length).toBeGreaterThan(0);
        else {
          expect(typeof value).toBe('object');
          pending.push(value);
        }
      }
    }
    expect(strings.length).toBeGreaterThan(100);
    expect(() => {
      (copy.status as { closed: string }).closed = 'Open';
    }).toThrow(TypeError);
  });

  it('keeps the formatters and MapLibre labels frozen too', () => {
    expect(Object.isFrozen(format)).toBe(true);
    expect(Object.isFrozen(shellFormat)).toBe(true);
    // The shell's one formatter, for the key's counts, is the one the rest use.
    expect(shellFormat.number).toBe(format.number);
    expect(Object.isFrozen(mapLocale)).toBe(true);
    expect(Object.isFrozen(STATUS_KEYS)).toBe(true);
    expect(Object.isFrozen(REASON_KEYS)).toBe(true);
  });

  it('has a string for every part of the site', () => {
    expect(copy.search.placeholder).toBe('Search a school, city, or ZIP');
    expect(Object.keys(copy.status)).toEqual(['closed', 'delayed', 'remote', 'earlyDismissal']);
    expect(copy.status.earlyDismissal).toBe('Early dismissal');
    expect(copy.open.label).toBe('Open');
    expect(copy.legend.glow).toBeTruthy();
    expect(copy.empty.noClosures).toBe('No weather closures today');
    expect(copy.actions.replay).toBe('Replay a past storm');
    expect(copy.replay.exit).toBeTruthy();
    expect(copy.detail.close).toBeTruthy();
    expect(copy.empty.noThreat).toBe('No weather threat in the forecast');
    expect(copy.actions.pin).toBe('Pin as my school');
    expect(copy.pin.unpin).toBeTruthy();
    expect(copy.actions.share).toBe('Share');
    expect(copy.share.copied).toBeTruthy();
    expect(copy.days).toEqual({ today: 'Today', tomorrow: 'Tomorrow' });
    expect(copy.nav.live).toBe('Live');
    expect(copy.live.updated).toBe('Updated');
    expect(copy.nav.listView).toBe('List view');
    expect(copy.nav.seasonStats).toBe('Season stats');
    expect(copy.nav.trackRecord).toBe('Track record');
    expect(copy.nav.about).toBe('About');
    expect(copy.live.offline).toBe('Offline');
    expect(copy.manifest.name).toBe(copy.appName);
    expect(copy.share.description).toBe(copy.meta.description);
  });

  it('says what the site is and how to read its lights in two short lines', () => {
    expect(Object.keys(copy.about)).toEqual(['what', 'glow']);
    for (const sentence of Object.values(copy.about)) {
      expect(sentence.split(/(?<=[.?])\s+/u)).toHaveLength(1);
      expect(sentence).toMatch(/^\p{Lu}[^.?]*\.$/u);
      expect(sentence.length).toBeLessThanOrEqual(60);
      // The wordmark over the menu names the site, and the field over it says how to search.
      expect(sentence).not.toContain(copy.appName);
      expect(sentence).not.toMatch(/search/iu);
    }
  });

  it('names the menu’s parts, what they set and what they count', () => {
    expect(copy.menu.label).toBe('Menu');
    expect([copy.menu.today, copy.menu.all]).toEqual(['Today', 'All']);
    expect([copy.menu.kinds, copy.menu.public, copy.menu.private]).toEqual([
      'Schools',
      'Public',
      'Private',
    ]);
    expect(copy.menu.onMap).toBe('On the map');
    expect([copy.menu.schools, copy.menu.districts]).toEqual(['Schools', 'Districts']);
    expect(copy.trackRecord.caption).toBe('Days with no school');
  });

  it.each(strings)('%s follows the house style', (_key, text) => {
    expect(problems(text)).toEqual([]);
  });

  it('names MapLibre controls by ids MapLibre knows', () => {
    const types = readFileSync(
      path.join(WEB_ROOT, 'node_modules', 'maplibre-gl', 'dist', 'maplibre-gl.d.ts'),
      'utf8',
    );
    const block = /declare const defaultLocale: \{([^}]*)\}/u.exec(types)?.[1] ?? '';
    const known = new Set([...block.matchAll(/"([\w.]+)": string;/gu)].map((match) => match[1]));
    expect(known.size).toBeGreaterThan(10);
    for (const [id, label] of Object.entries(mapLocale)) {
      expect([...known], id).toContain(id);
      expect(strings.map(([, text]) => text)).toContain(label);
    }
  });

  const schemaFile = (name: string): string => path.join(REPO_ROOT, 'schemas', name);
  const snake = (key: string): string => key.replace(/[A-Z]/gu, (c) => `_${c.toLowerCase()}`);

  it.skipIf(!existsSync(schemaFile('closings.schema.json')))(
    'numbers statuses and reasons as the published files do',
    () => {
      const schema = JSON.parse(readFileSync(schemaFile('closings.schema.json'), 'utf8')) as {
        $defs: Record<string, { enum: number[]; 'x-enum-names': string[] }>;
      };
      const status = schema.$defs.Status;
      const reason = schema.$defs.Reason;
      expect(STATUS_KEYS.map(snake)).toEqual(status?.['x-enum-names']);
      expect(STATUS_KEYS.map((_, code) => code)).toEqual(status?.enum);
      expect(REASON_KEYS.map(snake)).toEqual(reason?.['x-enum-names']);
      expect(REASON_KEYS.map((_, code) => code)).toEqual(reason?.enum);
      expect(Object.keys(copy.reason)).toEqual([...REASON_KEYS]);
    },
  );

  it.skipIf(!existsSync(schemaFile('alerts.schema.json')))(
    'names every alert hazard and level the alerts file uses',
    () => {
      const schema = JSON.parse(readFileSync(schemaFile('alerts.schema.json'), 'utf8')) as {
        $defs: Record<string, { enum: string[] }>;
      };
      expect(Object.keys(copy.hazard).sort()).toEqual(
        [...(schema.$defs.Hazard?.enum ?? [])].sort(),
      );
      expect(Object.keys(copy.alertLevel).sort()).toEqual(
        [...(schema.$defs.AlertLevel?.enum ?? [])].sort(),
      );
    },
  );

  const searchFormat = path.join(WEB_ROOT, 'src', 'search', 'format.ts');
  it.skipIf(!existsSync(searchFormat))('heads every kind of search result', async () => {
    const { KIND_CODES } = (await import(/* @vite-ignore */ searchFormat)) as {
      KIND_CODES: readonly string[];
    };
    expect(Object.keys(copy.search.sections).sort()).toEqual([...KIND_CODES].sort());
  });
});

describe('house style rules', () => {
  it.each([
    ['Closures may happen', 'may'],
    ['Schools MIGHT close', 'might'],
    ['Estimated arrival', 'estimate'],
    ['About 5 schools, approximately', 'approximate'],
    ['Disclaimer', 'disclaimer'],
    ['Search beta', 'beta'],
    ['Open source maps', 'source'],
    ['Sources', 'source'],
    ['Data provided by the state', 'data provided'],
    ['Powered   by maps', 'powered by'],
    ['Built on an algorithm', 'algorithm'],
    ['Sorry, no schools', 'sorry'],
    ['Please note the time', 'please note'],
    ['Accuracy 90%', 'accuracy'],
    ['Uses AI to see closings', 'AI'],
    ['A.I. picks', 'AI'],
    ['Likely closed', 'likely'],
    ['Our model says so', 'model'],
    ['The probability of a snow day', 'probability'],
    ['Three factors raise it', 'factor'],
    ['Scraped every hour', 'scrape'],
  ])('flags %j as banned phrase "%s"', (text, label) => {
    expect(problems(text)).toContain(`banned phrase "${label}"`);
  });

  it.each([
    ['Closed today!', 'exclamation mark'],
    ['Snow day ❄️', 'emoji'],
    ['Snow day ⛄', 'emoji'],
    ['Schools 🇺🇸', 'emoji'],
    ['Closed — today', 'em dash'],
    ['Closed -- today', 'em dash'],
    ['Search A School', 'Title Case "A"'],
    ['Season Stats', 'Title Case "Stats"'],
    ['CLOSED', 'all caps "CLOSED"'],
    ['closed today', 'starts with a lowercase letter'],
    [' Closed', 'leading or trailing space'],
    ['Closed  today', 'double space'],
    ['Closed\ntoday', 'tab or line break'],
    ["Don't close", 'straight quote: use ’ or “ ”'],
    ['Loading...', 'three dots: use …'],
    ['', 'empty string'],
  ])('flags %j with "%s"', (text, problem) => {
    expect(problems(text)).toContain(problem);
  });

  it.each([
    'May 4, 2026',
    'Mon, May 4',
    'Through May 12',
    'Said and done',
    'Hawaii',
    'Mayor',
    'Dismay',
    'Resources',
    'Remote learning today',
    `Live · 6:42${NBSP}AM`,
    `Offline · Updated Mon, Jan 12, 6:42${NBSP}PM`,
    'Snowlight maps schools. Search a school, city, or ZIP.',
    'Chance: 34%',
    'Closed 1,284 · Delayed 311',
    '2½-hour delay',
    'Don’t close',
    'K-12 schools across the US',
  ])('passes %j', (text) => {
    expect(problems(text)).toEqual([]);
  });

  it('reads "May" as a month only before a day number', () => {
    expect(problems('May close')).toContain('banned phrase "may"');
    expect(problems('Closed in May')).toContain('banned phrase "may"');
    expect(problems('Schools may 4 days')).toContain('banned phrase "may"');
  });

  it('matches "AI" only as a capitalized whole word', () => {
    expect(problems('AI')).toContain('banned phrase "AI"');
    expect(problems('Uses AI-driven maps')).toContain('banned phrase "AI"');
    expect(problems('Said')).toEqual([]);
    expect(problems('Air quality')).toEqual([]);
  });
});

describe('format', () => {
  const at = (iso: string): Date => new Date(iso);
  const nyc = 'America/New_York';

  describe('counts', () => {
    it('puts a status before its count, with thousands separators', () => {
      expect(format.count('closed', 1284)).toBe('Closed 1,284');
      expect(format.count('earlyDismissal', 4)).toBe('Early dismissal 4');
      expect(format.count('delayed', 0)).toBe('Delayed 0');
      expect(format.number(1_000_000)).toBe('1,000,000');
    });

    it('pluralizes schools and results', () => {
      expect(format.schools(0)).toBe('0 schools');
      expect(format.schools(1)).toBe('1 school');
      expect(format.schools(2)).toBe('2 schools');
      expect(format.schools(30_000)).toBe('30,000 schools');
      expect(format.results(0)).toBe(copy.search.noResults);
      expect(format.results(1)).toBe('1 result');
      expect(format.results(1284)).toBe('1,284 results');
    });

    it('sums up the statuses that have schools, in code order', () => {
      expect(format.summary({ earlyDismissal: 4, closed: 1284, remote: 0, delayed: 311 })).toBe(
        'Closed 1,284 · Delayed 311 · Early dismissal 4',
      );
      expect(format.summary({ closed: 0 })).toBeNull();
      expect(format.summary({})).toBeNull();
    });

    it('refuses counts that are not whole numbers of 0 or more', () => {
      for (const bad of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY, 2 ** 53]) {
        expect(() => format.number(bad)).toThrow(RangeError);
        expect(() => format.schools(bad)).toThrow(RangeError);
      }
      expect(() => format.summary({ closed: -3 })).toThrow(RangeError);
    });
  });

  describe('times', () => {
    it('writes the live update time in the given time zone', () => {
      const update = at('2026-01-12T11:42:00Z');
      expect(format.liveAt(update, nyc)).toBe(`Live · 6:42${NBSP}AM`);
      // A no-break space keeps "6:42 AM" on one line; otherwise it reads exactly as specified.
      expect(format.liveAt(update, nyc).replace(NBSP, ' ')).toBe('Live · 6:42 AM');
      expect(format.liveAt(update, 'America/Chicago')).toBe(`Live · 5:42${NBSP}AM`);
      expect(format.liveAt(update, 'America/Los_Angeles')).toBe(`Live · 3:42${NBSP}AM`);
      expect(format.time(update, 'UTC')).toBe(`11:42${NBSP}AM`);
    });

    it('handles midnight, noon and daylight saving time', () => {
      expect(format.time(at('2026-01-12T05:00:00Z'), nyc)).toBe(`12:00${NBSP}AM`);
      expect(format.time(at('2026-01-12T17:00:00Z'), nyc)).toBe(`12:00${NBSP}PM`);
      expect(format.time(at('2026-01-13T04:59:00Z'), nyc)).toBe(`11:59${NBSP}PM`);
      // Spring forward on Mar 8, 2026: 2:00 AM EST becomes 3:00 AM EDT.
      expect(format.time(at('2026-03-08T06:59:00Z'), nyc)).toBe(`1:59${NBSP}AM`);
      expect(format.time(at('2026-03-08T07:00:00Z'), nyc)).toBe(`3:00${NBSP}AM`);
      // Fall back on Nov 1, 2026: 1:30 AM happens twice.
      expect(format.time(at('2026-11-01T05:30:00Z'), nyc)).toBe(`1:30${NBSP}AM`);
      expect(format.time(at('2026-11-01T06:30:00Z'), nyc)).toBe(`1:30${NBSP}AM`);
      // Arizona keeps standard time all year.
      expect(format.time(at('2026-07-01T19:00:00Z'), 'America/Phoenix')).toBe(`12:00${NBSP}PM`);
    });

    it('adds the day when an update is from another local day', () => {
      const update = at('2026-01-12T11:42:00Z');
      expect(format.updatedAt(update, nyc, at('2026-01-12T20:00:00Z'))).toBe(
        `Updated 6:42${NBSP}AM`,
      );
      expect(format.updatedAt(update, nyc, at('2026-01-13T12:00:00Z'))).toBe(
        `Updated Mon, Jan 12, 6:42${NBSP}AM`,
      );
      // 02:00 UTC on Jan 13 is 9 PM on Jan 12 in New York: the day comes from the zone, not UTC.
      expect(format.updatedAt(at('2026-01-13T02:00:00Z'), nyc, at('2026-01-13T12:00:00Z'))).toBe(
        `Updated Mon, Jan 12, 9:00${NBSP}PM`,
      );
      expect(format.offline(update, nyc, update)).toBe(`Offline · Updated 6:42${NBSP}AM`);
      expect(format.posted(at('2026-01-12T01:30:00Z'), nyc, update)).toBe(
        `Posted Sun, Jan 11, 8:30${NBSP}PM`,
      );
    });

    it('turns minutes after midnight into a wall-clock time', () => {
      expect(format.clock(0)).toBe(`12:00${NBSP}AM`);
      expect(format.clock(630)).toBe(`10:30${NBSP}AM`);
      expect(format.clock(720)).toBe(`12:00${NBSP}PM`);
      expect(format.clock(1439)).toBe(`11:59${NBSP}PM`);
      for (const bad of [-1, 1440, 12.5, Number.NaN])
        expect(() => format.clock(bad)).toThrow(RangeError);
    });

    it('refuses an unknown time zone or an invalid date', () => {
      expect(() => format.liveAt(at('2026-01-12T11:42:00Z'), 'Mars/Olympus_Mons')).toThrow(
        RangeError,
      );
      expect(() => format.time(new Date(Number.NaN), nyc)).toThrow(RangeError);
    });
  });

  describe('days', () => {
    it('writes calendar days without shifting them by time zone', () => {
      expect(format.day('2026-01-12')).toBe('Mon, Jan 12');
      expect(format.day('2026-05-04')).toBe('Mon, May 4');
      expect(format.dayWithYear('2026-12-31')).toBe('Dec 31, 2026');
      expect(format.through('2026-01-12')).toBe('Through Jan 12');
      expect(format.day('2028-02-29')).toBe('Tue, Feb 29');
    });

    it('refuses anything that is not a real YYYY-MM-DD day', () => {
      for (const bad of ['2026-02-29', '2026-13-01', '2026-1-12', '12/01/2026', '']) {
        expect(() => format.day(bad)).toThrow(RangeError);
      }
    });

    it('spans the days a track record covers', () => {
      expect(format.span('2026-01-05', '2026-03-02')).toBe('Jan 5 to Mar 2, 2026');
      expect(format.span('2025-12-01', '2026-03-02')).toBe('Dec 1, 2025 to Mar 2, 2026');
      expect(format.span('2026-03-02', '2026-03-02')).toBe('Mar 2, 2026');
      expect(() => format.span('2026-03-02', '2026-01-05')).toThrow(RangeError);
    });

    it('writes a school year as its two years', () => {
      expect(format.season('2025-2026')).toBe('2025–26');
      expect(format.season('2099-2100')).toBe('2099–00');
      for (const bad of ['2025-2027', '2025', '2025–2026', '']) {
        expect(() => format.season(bad)).toThrow(RangeError);
      }
    });

    it('words a status for today, tomorrow and later days in the school’s time zone', () => {
      // 03:30 UTC on Jan 13 is still the evening of Jan 12 in New York.
      const now = at('2026-01-13T03:30:00Z');
      expect(format.statusOn('closed', '2026-01-12', now, nyc)).toBe('Closed today');
      expect(format.statusOn('delayed', '2026-01-13', now, nyc)).toBe('Delayed start tomorrow');
      expect(format.statusOn('remote', '2026-01-13', now, 'UTC')).toBe('Remote learning today');
      expect(format.statusOn('earlyDismissal', '2026-01-16', now, nyc)).toBe(
        'Early dismissal Fri, Jan 16',
      );
    });
  });

  describe('delays and dismissals', () => {
    it.each([
      [120, null, '2-hour delay'],
      [60, null, '1-hour delay'],
      [90, null, '90-minute delay'],
      [45, null, '45-minute delay'],
      [150, null, '2½-hour delay'],
      [135, null, '135-minute delay'],
      [null, 600, `Starts at 10:00${NBSP}AM`],
      [90, 570, `90-minute delay · Starts at 9:30${NBSP}AM`],
    ] as const)('delay(%j, %j) is %j', (shift, clockMinute, expected) => {
      expect(format.delay(shift, clockMinute)).toBe(expected);
    });

    it.each([
      [120, null, '2 hours early'],
      [60, null, '1 hour early'],
      [1, null, '1 minute early'],
      [90, null, '90 minutes early'],
      [150, null, '2½ hours early'],
      [null, 750, `Dismissal at 12:30${NBSP}PM`],
      [90, 750, `Dismissal at 12:30${NBSP}PM · 90 minutes early`],
    ] as const)('dismissal(%j, %j) is %j', (shift, clockMinute, expected) => {
      expect(format.dismissal(shift, clockMinute)).toBe(expected);
    });

    it('says nothing when a listing gave no times, and refuses impossible ones', () => {
      expect(format.delay(null, null)).toBeNull();
      expect(format.dismissal(null, null)).toBeNull();
      for (const bad of [0, -30, 721, 1.5, Number.NaN]) {
        expect(() => format.delay(bad, null)).toThrow(RangeError);
        expect(() => format.dismissal(bad, null)).toThrow(RangeError);
      }
    });
  });

  describe('a school’s grades and phone number', () => {
    it('reads the grades a school teaches from its lowest and highest NCES codes', () => {
      expect(format.grades('PK', '12')).toBe('PK–12');
      expect(format.grades('KG', '05')).toBe('K–5');
      expect(format.grades('09', '12')).toBe('9–12');
      expect(format.grades('TK', '08')).toBe('TK–8');
      expect(format.grades('KG', 'KG')).toBe('K');
      expect(format.grades('13', '13')).toBe('13');
      for (const bad of ['T1', '00', '14', 'K', '', '5']) {
        expect(() => format.grades(bad, '12')).toThrow(RangeError);
      }
    });

    it('writes a distance in miles, to a tenth under ten miles', () => {
      expect(format.miles(0)).toBe(`0.1${NBSP}mi`);
      expect(format.miles(643)).toBe(`0.4${NBSP}mi`);
      expect(format.miles(1609.344)).toBe(`1.0${NBSP}mi`);
      expect(format.miles(15_900)).toBe(`9.9${NBSP}mi`);
      expect(format.miles(16_100)).toBe(`10${NBSP}mi`);
      expect(format.miles(1_609_344)).toBe(`1,000${NBSP}mi`);
      for (const bad of [-1, Number.NaN, Infinity]) {
        expect(() => format.miles(bad)).toThrow(RangeError);
      }
    });

    it('writes a phone number as it is dialed in the US, never broken across lines', () => {
      expect(format.phone('8169361230')).toBe(`(816)${NBSP}936-1230`);
      for (const bad of ['816936123', '816-936-1230', '81693612300']) {
        expect(() => format.phone(bad)).toThrow(RangeError);
      }
    });
  });

  describe('chances and the track record', () => {
    it('writes a probability as a whole percentage that never claims certainty', () => {
      expect(format.chance(0.34)).toBe('34%');
      expect(format.chance(0.005)).toBe('1%');
      expect(format.chance(0.004)).toBe('<1%');
      expect(format.chance(0)).toBe('<1%');
      expect(format.chance(0.994)).toBe('99%');
      expect(format.chance(0.995)).toBe('>99%');
      expect(format.chance(1)).toBe('>99%');
      for (const bad of [-0.01, 1.01, Number.NaN])
        expect(() => format.chance(bad)).toThrow(RangeError);
    });

    it('writes bins, hit counts and lead times', () => {
      expect(format.percentRange(40, 50)).toBe('40–50%');
      expect(format.percentRange(90, 100)).toBe('90–100%');
      expect(() => format.percentRange(50, 40)).toThrow(RangeError);
      expect(format.outOf(9, 20)).toBe('9 of 20');
      expect(format.outOf(1284, 30_000)).toBe('1,284 of 30,000');
      expect(() => format.outOf(21, 20)).toThrow(RangeError);
      expect(format.lead(0)).toBe(copy.trackRecord.lead.sameMorning);
      expect(format.lead(1)).toBe(copy.trackRecord.lead.dayBefore);
      expect(format.lead(2)).toBe(copy.trackRecord.lead.twoDaysBefore);
      expect(() => format.lead(3)).toThrow(RangeError);
    });
  });

  describe('the chance section', () => {
    const kc = 'America/Chicago';
    /** The school's clock, read where the school is; and read from New York. */
    const here: Zones = { school: kc, viewer: kc };
    const east: Zones = { school: kc, viewer: 'America/New_York' };
    /** Monday Jan 12, 2026, 9:05 PM in Kansas City. */
    const evening = at('2026-01-13T03:05:00Z');
    const morning = at('2026-01-13T12:20:00Z');
    const reason = (input: ReasonInput, now = evening, zones = here): string =>
      chanceFormat.reason(input, 'Riverside', now, zones);
    const record = { closed: 4, remote: 0, days: 5, inches: 6 };

    it('heads the section with the chance and its day', () => {
      expect(Object.isFrozen(chanceFormat)).toBe(true);
      expect(Object.isFrozen(chanceCopy)).toBe(true);
      expect(allProblems(copyLeaves(chanceCopy).map(([, text]) => text))).toEqual([]);
      expect(chanceFormat.weekday('2026-01-13')).toBe('Tuesday');
      expect(chanceFormat.chanceOn('2026-01-14')).toBe('Chance of no school Wednesday');
      expect(chanceFormat.chanceNumber(0.64)).toBe('64');
      expect(chanceFormat.chanceNumber(0.01)).toBe('1');
      expect(chanceFormat.chanceNumber(0.99)).toBe('99');
      expect(chanceFormat.howWeGot(0.64)).toBe('How we got 64%');
      expect(chanceFormat.delayInstead(0.18)).toBe('18% chance of a delayed start instead');
      expect(chanceFormat.points(16)).toBe('+16');
      expect(chanceFormat.points(-3)).toBe('−3');
      expect(() => chanceFormat.points(0)).toThrow(RangeError);
      expect(() => chanceFormat.points(1.5)).toThrow(RangeError);
    });

    it('says what moved the chance, and since when, on the school’s clock', () => {
      const moved = (
        previous: number,
        current: number,
        then: string,
        now = evening,
        zones = here,
      ) => chanceFormat.moved({ previous, current, at: at(then), now, zones });
      expect(moved(0.41, 0.64, '2026-01-12T23:00:00Z')).toBe(`Up from 41% at 5${NBSP}PM`);
      expect(moved(0.7, 0.64, '2026-01-12T23:30:00Z')).toBe(`Down from 70% at 5:30${NBSP}PM`);
      expect(moved(0.64, 0.64, '2026-01-12T23:00:00Z')).toBe(`Same as at 5${NBSP}PM`);
      // Read from New York: the school's 5 PM, with its zone.
      expect(moved(0.41, 0.64, '2026-01-12T23:00:00Z', evening, east)).toBe(
        `Up from 41% at 5${NBSP}PM${NBSP}CT`,
      );
      // The morning after: the run of the evening before is last night's.
      expect(moved(0.3, 0.22, '2026-01-13T03:00:00Z', morning)).toBe('Down from 30% last night');
      expect(moved(0.1, 0.22, '2026-01-12T18:00:00Z', morning)).toBe('Up from 10% yesterday');
      expect(moved(0.1, 0.22, '2026-01-10T18:00:00Z', morning)).toBe('Up from 10% on Saturday');
      expect(moved(0.1, 0.22, '2026-01-06T18:00:00Z', morning)).toBeNull();
      // A run from after now says nothing.
      expect(moved(0.1, 0.22, '2026-01-13T13:00:00Z', morning)).toBeNull();
    });

    it('words the timeline: who posted, what happened, and the usual time', () => {
      const posted = (status: StatusKey): string =>
        chanceFormat.neighborPosted('Riverside', status, '2026-01-13');
      expect(posted('closed')).toBe('Riverside canceled Tuesday');
      expect(posted('delayed')).toBe('Riverside starts late Tuesday');
      expect(posted('remote')).toBe('Riverside is remote Tuesday');
      expect(posted('earlyDismissal')).toBe('Riverside lets out early Tuesday');
      expect(chanceFormat.usuallyAnnounces('Riverside')).toBe('Riverside usually announces');
      expect(chanceFormat.weatherEvent('snow_started', null)).toBe('Snow started');
      expect(chanceFormat.weatherEvent('snow_stopped', 8)).toBe('Snow stopped, 8 inches in all');
      expect(chanceFormat.weatherEvent('snow_stopped', 1)).toBe('Snow stopped, 1 inch in all');
      // Within the last day, its time; before that, its day.
      expect(chanceFormat.momentTime(at('2026-01-13T02:41:00Z'), evening, here)).toBe(
        `8:41${NBSP}PM`,
      );
      // The zone after a plain space, to take its own line under the time in the narrow column.
      expect(chanceFormat.momentTime(at('2026-01-13T02:41:00Z'), evening, east)).toBe(
        `8:41${NBSP}PM CT`,
      );
      expect(chanceFormat.momentTime(at('2026-01-12T03:04:00Z'), evening, here)).toBe(
        'Sun, Jan 11',
      );
    });

    it('words the chart: its values, its times and its key', () => {
      const span = (from: string, to: string, zones = here): string =>
        chanceFormat.hourSpan(at(from), at(to), zones);
      expect(chanceFormat.inches(7.5)).toBe(`7.5${NBSP}in`);
      expect(chanceFormat.inches(6, 9)).toBe(`6 to 9${NBSP}in`);
      expect(chanceFormat.inches(0.25)).toBe(`0.3${NBSP}in`);
      // The site's one minus sign.
      expect(chanceFormat.degrees(-8)).toBe(`−8${NBSP}F`);
      expect(chanceFormat.degrees(-0.4)).toBe(`0${NBSP}F`);
      expect(chanceFormat.degrees(12)).toBe(`12${NBSP}F`);
      expect(chanceFormat.shortTime(at('2026-01-13T13:00:00Z'), kc)).toBe(`7${NBSP}AM`);
      expect(chanceFormat.shortTime(at('2026-01-13T06:00:00Z'), kc)).toBe(`12${NBSP}AM`);
      expect(chanceFormat.shortTime(at('2026-01-13T11:30:00Z'), kc)).toBe(`5:30${NBSP}AM`);
      expect(chanceFormat.clock(at('2026-01-13T13:00:00Z'), east)).toBe(`7${NBSP}AM${NBSP}CT`);
      expect(span('2026-01-13T08:00:00Z', '2026-01-13T11:00:00Z')).toBe(`2 to 5${NBSP}AM`);
      expect(span('2026-01-13T05:00:00Z', '2026-01-13T08:00:00Z')).toBe(
        `11${NBSP}PM to 2${NBSP}AM`,
      );
      expect(span('2026-01-13T08:30:00Z', '2026-01-13T11:00:00Z')).toBe(`2:30 to 5${NBSP}AM`);
      expect(span('2026-01-13T08:00:00Z', '2026-01-13T11:00:00Z', east)).toBe(
        `2 to 5${NBSP}AM${NBSP}CT`,
      );
      // On the chart, counting down while it is to come, unbroken; no weekday on one night.
      expect(chanceFormat.announcesKey(at('2026-01-13T11:30:00Z'), here, evening)).toBe(
        `Usually announces 5:30${NBSP}AM, in${NBSP}8h${NBSP}25m`,
      );
      expect(chanceFormat.announcesKey(at('2026-01-14T11:30:00Z'), east, evening)).toBe(
        `Usually announces 5:30${NBSP}AM${NBSP}CT, in${NBSP}32h${NBSP}25m`,
      );
      expect(chanceFormat.announcesKey(at('2026-01-13T03:50:00Z'), here, evening)).toBe(
        `Usually announces 9:50${NBSP}PM, in${NBSP}45m`,
      );
      expect(
        chanceFormat.announcesKey(at('2026-01-13T11:30:00Z'), here, at('2026-01-13T11:30:00Z')),
      ).toBe(`Usually announces 5:30${NBSP}AM`);
      expect(chanceFormat.district('300')).toBe('District 300');
      expect(chanceFormat.announcesKey(at('2026-01-13T11:30:00Z'), here)).toBe(
        `Usually announces 5:30${NBSP}AM`,
      );
      expect(
        chanceFormat.heaviestKey(at('2026-01-13T08:00:00Z'), at('2026-01-13T11:00:00Z'), here),
      ).toBe(`Heaviest snow 2 to 5${NBSP}AM`);
      expect(chanceFormat.busesKey(`6 to 9${NBSP}in`, at('2026-01-13T13:00:00Z'), east)).toEqual({
        value: `6 to 9${NBSP}in`,
        rest: ` when buses run at 7${NBSP}AM${NBSP}CT`,
      });
      expect(chanceFormat.chartSummary('snow_total', at('2026-01-13T13:00:00Z'), 6, 9, here)).toBe(
        `By 7${NBSP}AM, when the buses run, the forecast has 6 to 9 inches of snow on the ground.`,
      );
      expect(
        chanceFormat.chartSummary('wind_chill', at('2026-01-14T13:00:00Z'), -8, -8, here),
      ).toBe(`At 7${NBSP}AM, when the buses run, the forecast has it feeling like −8${NBSP}F.`);
    });

    it('starts the sum from the district’s own rate, or its neighbors’, as a count', () => {
      // A count read at a glance, true to the whole percent.
      expect(chanceFormat.shareOf(30)).toEqual({ some: 3, of: 10, more: false });
      expect(chanceFormat.shareOf(25)).toEqual({ some: 1, of: 4, more: false });
      expect(chanceFormat.shareOf(33)).toEqual({ some: 1, of: 3, more: false });
      expect(chanceFormat.shareOf(67)).toEqual({ some: 2, of: 3, more: false });
      expect(chanceFormat.shareOf(1)).toEqual({ some: 1, of: 100, more: false });
      expect(chanceFormat.shareOf(3)).toEqual({ some: 1, of: 33, more: false });
      expect(chanceFormat.shareOf(7)).toEqual({ some: 1, of: 14, more: false });
      expect(chanceFormat.shareOf(95)).toEqual({ some: 19, of: 20, more: false });
      expect(chanceFormat.shareOf(99)).toEqual({ some: 99, of: 100, more: false });
      // Else the most such a count it is sure to be more than: never "about", never "16 in 25".
      expect(chanceFormat.shareOf(64)).toEqual({ some: 3, of: 5, more: true });
      expect(chanceFormat.shareOf(45)).toEqual({ some: 2, of: 5, more: true });
      expect(chanceFormat.shareOf(12)).toEqual({ some: 1, of: 9, more: true });
      expect(chanceFormat.shareOf(97)).toEqual({ some: 19, of: 20, more: true });
      const glance = new Set(['1/2', '1/3', '2/3', '1/4', '3/4', '2/5', '3/5', '4/5', '3/10']);
      for (const share of ['7/10', '9/10', '19/20', '49/50', '99/100']) glance.add(share);
      for (let percent = 1; percent <= 99; percent++) {
        const { some, of, more } = chanceFormat.shareOf(percent);
        const share = (some * 100) / of;
        // Said exactly, it rounds to the percent; said as "more than", the percent is surely more.
        if (more) expect(share, String(percent)).toBeLessThanOrEqual(percent - 0.5);
        else expect(Math.round(share), String(percent)).toBe(percent);
        // A glance: one in so many, or a few in at most ten, or near all.
        expect(some === 1 || glance.has(`${String(some)}/${String(of)}`), String(percent)).toBe(
          true,
        );
      }
      expect(() => chanceFormat.shareOf(0)).toThrow(RangeError);
      const base = (input: BaseInput): string => chanceFormat.baseReason(input, 'Riverside');
      expect(base({ kind: 'alert', points: 30, alert: 'winter_storm_warning' })).toBe(
        'Riverside cancels for 3 in 10 winter storm warnings.',
      );
      expect(base({ kind: 'alert', points: 33, alert: 'ice_storm_warning' })).toBe(
        'Riverside cancels for 1 in 3 ice storm warnings.',
      );
      expect(base({ kind: 'alert', points: 64, alert: 'winter_storm_warning' })).toBe(
        'Riverside cancels for more than 3 in 5 winter storm warnings.',
      );
      expect(base({ kind: 'similar_days', points: 12 })).toBe(
        'On days like this, Riverside closes more than 1 time in 9.',
      );
      expect(base({ kind: 'alert', points: 0, alert: 'winter_weather_advisory' })).toBe(
        'Riverside almost never cancels for winter weather advisories.',
      );
      expect(base({ kind: 'alert', points: 100, alert: 'blizzard_warning' })).toBe(
        'Riverside almost always cancels for blizzard warnings.',
      );
      expect(base({ kind: 'day_after', points: 25 })).toBe(
        'After a snow day, Riverside stays closed the next day 1 time in 4.',
      );
      expect(base({ kind: 'day_after', points: 60 })).toBe(
        'After a snow day, Riverside stays closed the next day 3 times in 5.',
      );
      expect(base({ kind: 'similar_days', points: 20 })).toBe(
        'On days like this, Riverside closes 1 time in 5.',
      );
      expect(base({ kind: 'similar_days', points: 0 })).toBe(
        'On days like this, Riverside almost never closes.',
      );
      // A district with too short a history of its own: the districts around it, said so.
      expect(base({ kind: 'pooled', points: 30, scope: 'nearby', alert: null })).toBe(
        'Districts near Riverside close 3 times in 10 on days like this.',
      );
      expect(
        base({ kind: 'pooled', points: 30, scope: 'county', alert: 'winter_storm_warning' }),
      ).toBe('Districts in Riverside’s county close for 3 in 10 winter storm warnings.');
      expect(base({ kind: 'pooled', points: 3, scope: 'state', alert: null })).toBe(
        'Districts in Riverside’s state close 1 time in 33 on days like this.',
      );
      expect(base({ kind: 'pooled', points: 0, scope: 'region', alert: null })).toBe(
        'Districts in Riverside’s region almost never close on days like this.',
      );
      expect(() =>
        chanceFormat.baseReason({ kind: 'alert', points: 30, alert: 'fog' as never }, 'Riverside'),
      ).toThrow(RangeError);
    });

    it('says every kind of reason, each way it can go, a forecast as the forecast’s claim', () => {
      const buses = at('2026-01-13T13:00:00Z');
      const snow = (
        points: number,
        low: number,
        high: number,
        overnight: boolean,
        counted: typeof record | null,
      ): string => reason({ kind: 'snow_total', points, low, high, overnight, record: counted });
      expect(snow(16, 6, 9, true, record)).toBe(
        'The forecast has 6 to 9 inches overnight, more than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
      );
      expect(snow(-4, 1, 1, false, null)).toBe('The forecast has 1 inch, less than most storms.');
      expect(snow(8, 4, 6, false, { closed: 3, remote: 0, days: 3, inches: 4 })).toBe(
        'The forecast has 4 to 6 inches, more than most storms. It closed each of the last 3 times it got 4 inches or more.',
      );
      expect(snow(-6, 2, 3, true, { closed: 0, remote: 0, days: 1, inches: 2 })).toBe(
        'The forecast has 2 to 3 inches overnight, less than most storms. It stayed open the last time it got 2 inches or more.',
      );
      expect(snow(6, 2, 3, true, { closed: 1, remote: 0, days: 1, inches: 2 })).toBe(
        'The forecast has 2 to 3 inches overnight, more than most storms. It closed the last time it got 2 inches or more.',
      );
      expect(reason({ kind: 'record', points: 4, record })).toBe(
        'Riverside closed 4 of the last 5 times it got 6 inches or more.',
      );
      expect(
        reason({
          kind: 'record',
          points: -4,
          record: { closed: 0, remote: 0, days: 4, inches: 3 },
        }),
      ).toBe('Riverside closed none of the last 4 times it got 3 inches or more.');
      // A remote day is not a closing.
      expect(
        reason({ kind: 'record', points: 4, record: { closed: 4, remote: 1, days: 5, inches: 6 } }),
      ).toBe('Riverside closed or went remote 4 of the last 5 times it got 6 inches or more.');
      expect(
        reason({ kind: 'record', points: 4, record: { closed: 4, remote: 4, days: 5, inches: 6 } }),
      ).toBe('Riverside went remote 4 of the last 5 times it got 6 inches or more.');
      const next = (names: string[] | null, count: number, status: StatusKey): string =>
        reason({ kind: 'neighbors', points: 9, names, count, status });
      expect(next(['Blue Valley', 'Olathe'], 2, 'closed')).toBe(
        'Blue Valley and Olathe, next door, canceled.',
      );
      expect(next(['Olathe'], 1, 'delayed')).toBe('Olathe, next door, delayed the start.');
      expect(next(['Blue Valley', 'Olathe', 'De Soto'], 3, 'closed')).toBe(
        'Blue Valley, Olathe and De Soto, next door, canceled.',
      );
      expect(next(['A1', 'B2', 'C3', 'D4', 'E5'], 5, 'remote')).toBe(
        'A1, B2 and 3 more, next door, went remote.',
      );
      expect(next(null, 1, 'earlyDismissal')).toBe(
        'A district next door called an early dismissal.',
      );
      expect(next(null, 3, 'closed')).toBe('3 districts next door canceled.');
      const timing = (start: string, end: string, when: Date | null = buses): string =>
        reason({ kind: 'timing', points: 7, start: at(start), end: at(end), buses: when });
      expect(timing('2026-01-13T08:00:00Z', '2026-01-13T11:00:00Z')).toBe(
        `The forecast has the heaviest snow 2 to 5${NBSP}AM, just before the buses.`,
      );
      expect(timing('2026-01-13T12:00:00Z', '2026-01-13T15:00:00Z')).toBe(
        `The forecast has the heaviest snow 6 to 9${NBSP}AM, while the buses are out.`,
      );
      expect(timing('2026-01-13T03:00:00Z', '2026-01-13T07:00:00Z')).toBe(
        `The forecast has the heaviest snow 9${NBSP}PM to 1${NBSP}AM, well before the buses.`,
      );
      expect(timing('2026-01-13T16:00:00Z', '2026-01-13T20:00:00Z')).toBe(
        `The forecast has the heaviest snow 10${NBSP}AM to 2${NBSP}PM, after the buses are out.`,
      );
      expect(timing('2026-01-13T08:00:00Z', '2026-01-13T11:00:00Z', null)).toBe(
        `The forecast has the heaviest snow 2 to 5${NBSP}AM.`,
      );
      expect(reason({ kind: 'wind_chill', points: 5, feelsLike: -4 })).toBe(
        `The forecast has a wind chill of −4${NBSP}F at the bus stop.`,
      );
      expect(reason({ kind: 'cold', points: 6, feelsLike: -8, day: '2026-01-14' })).toBe(
        `The forecast has it feeling like −8${NBSP}F at the bus stop Wednesday morning.`,
      );
      const stops = (then: string, now = evening, day = '2026-01-13', zones = here): string =>
        reason({ kind: 'snow_stops', points: -3, at: at(then), buses, day }, now, zones);
      expect(stops('2026-01-13T11:00:00Z')).toBe(
        `The forecast has the snow ending by 5${NBSP}AM, a head start for the plows.`,
      );
      // Ending as the buses go out is no head start; the bus hour is left to the chart that says it.
      expect(stops('2026-01-13T13:00:00Z')).toBe(
        `The forecast has the snow ending at 7${NBSP}AM, as the buses go out.`,
      );
      expect(
        reason(
          {
            kind: 'snow_stops',
            points: -3,
            at: at('2026-01-13T13:00:00Z'),
            buses,
            day: '2026-01-13',
            busesSaid: true,
          },
          evening,
          here,
        ),
      ).toBe('The forecast has the snow ending as the buses go out.');
      expect(stops('2026-01-13T15:00:00Z')).toBe(
        `The forecast has snow until 9${NBSP}AM, after the buses go out.`,
      );
      expect(stops('2026-01-13T12:00:00Z', morning, '2026-01-14')).toBe(
        `The snow stopped at 6${NBSP}AM, a full day for the plows.`,
      );
      expect(stops('2026-01-13T09:00:00Z', morning)).toBe(
        `The snow stopped at 3${NBSP}AM, a head start for the plows.`,
      );
      // The school's day, however late it is where the viewer is: 11:30 PM Monday in Kansas
      // City is Tuesday in New York, and the snow that stopped then stopped the day before.
      expect(stops('2026-01-13T05:30:00Z', morning, '2026-01-13', east)).toBe(
        `The snow stopped at 11:30${NBSP}PM${NBSP}CT, a full day for the plows.`,
      );
      expect(reason({ kind: 'sun', points: -5, day: '2026-01-14' }, morning)).toBe(
        'The forecast has sun this afternoon to help melt the ice.',
      );
      expect(reason({ kind: 'sun', points: -5, day: '2026-01-13' }, evening)).toBe(
        'Sun earlier today helped melt the ice.',
      );
      // The afternoon before the day the chance is for: yesterday's, once that day has begun.
      expect(reason({ kind: 'sun', points: -5, day: '2026-01-13' }, morning)).toBe(
        'Sun yesterday afternoon helped melt the ice.',
      );
      expect(reason({ kind: 'sun', points: -5, day: '2026-01-14' }, evening)).toBe(
        'The forecast has sun Tuesday afternoon to help melt the ice.',
      );
      // What the chart or the timeline already says, the sum only names.
      expect(
        reason({
          kind: 'snow_total',
          points: 16,
          low: 6,
          high: 9,
          overnight: true,
          record,
          said: true,
        }),
      ).toBe(
        'More snow than most storms. It closed 4 of the last 5 times it got 6 inches or more.',
      );
      expect(
        reason({
          kind: 'snow_total',
          points: -4,
          low: 1,
          high: 1,
          overnight: false,
          record: null,
          said: true,
        }),
      ).toBe('Less snow than most storms.');
      expect(
        reason({
          kind: 'neighbors',
          points: 9,
          names: ['Olathe'],
          count: 1,
          status: 'closed',
          said: true,
        }),
      ).toBe('A district next door canceled.');
      expect(
        reason({
          kind: 'neighbors',
          points: 9,
          names: null,
          count: 3,
          status: 'remote',
          said: true,
        }),
      ).toBe('Districts next door went remote.');
      const named = (start: string, end: string): string =>
        reason({ kind: 'timing', points: 7, start: at(start), end: at(end), buses, said: true });
      expect(named('2026-01-13T08:00:00Z', '2026-01-13T11:00:00Z')).toBe(
        'Heaviest snow just before the buses.',
      );
      expect(named('2026-01-13T12:00:00Z', '2026-01-13T15:00:00Z')).toBe(
        'Heaviest snow while the buses are out.',
      );
      expect(named('2026-01-13T03:00:00Z', '2026-01-13T07:00:00Z')).toBe(
        'Heaviest snow well before the buses.',
      );
      expect(named('2026-01-13T16:00:00Z', '2026-01-13T20:00:00Z')).toBe(
        'Heaviest snow after the buses are out.',
      );
      // Without the buses there is nothing to set the hours against: they stay.
      expect(
        reason({
          kind: 'timing',
          points: 7,
          start: at('2026-01-13T08:00:00Z'),
          end: at('2026-01-13T11:00:00Z'),
          buses: null,
          said: true,
        }),
      ).toBe(`The forecast has the heaviest snow 2 to 5${NBSP}AM.`);
      expect(reason({ kind: 'wind_chill', points: 5, feelsLike: -4, said: true })).toBe(
        'Wind chill at the bus stop.',
      );
      expect(
        reason({ kind: 'cold', points: 6, feelsLike: -8, day: '2026-01-14', said: true }),
      ).toBe('Cold at the bus stop Wednesday morning.');
      const stopped = (then: string, day: string): string =>
        reason({ kind: 'snow_stops', points: -3, at: at(then), buses, day, said: true }, morning);
      expect(stopped('2026-01-13T12:00:00Z', '2026-01-14')).toBe(
        'The snow stopped, a full day for the plows.',
      );
      expect(stopped('2026-01-13T09:00:00Z', '2026-01-13')).toBe(
        'The snow stopped, a head start for the plows.',
      );
      expect(reason({ kind: 'icy_roads', points: 4, inches: 8 })).toBe(
        'Side streets stay icy after 8 inches of snow.',
      );
      expect(reason({ kind: 'ice', points: 9, inches: 0.2 })).toBe(
        'The forecast has freezing rain leaving 0.2 inches of ice.',
      );
      // Numbers the sentences cannot hold.
      expect(() => reason({ kind: 'sun', points: 0, day: '2026-01-14' })).toThrow(RangeError);
      expect(() => next(null, 0, 'closed')).toThrow(RangeError);
      expect(() =>
        reason({ kind: 'record', points: 3, record: { closed: 6, remote: 0, days: 5, inches: 6 } }),
      ).toThrow(RangeError);
      expect(() => timing('2026-01-13T11:00:00Z', '2026-01-13T08:00:00Z')).toThrow(RangeError);
    });

    it('follows the house style, with the words around a district’s name', () => {
      const outputs: string[] = [];
      // Every school is in a US time zone; the viewer may be anywhere.
      for (const zone of ZONES.filter(
        (name) => name.startsWith('America/') || name.startsWith('Pacific/'),
      )) {
        const zones = { school: zone, viewer: 'America/Chicago' };
        for (let hour = 0; hour < 48; hour++) {
          const then = new Date(evening.getTime() + hour * 3_600_000);
          const countdown = chanceFormat.countdown(then, evening, zone);
          const key = chanceFormat.busesKey(chanceFormat.inches(6, 9), then, zones);
          outputs.push(
            chanceFormat.shortTime(then, zone),
            chanceFormat.clock(then, zones),
            chanceFormat.announcesKey(then, zones),
            chanceFormat.heaviestKey(evening, then, zones),
            `${key.value}${key.rest}`,
            chanceFormat.hourSpan(evening, then, zones),
            chanceFormat.momentTime(then, morning, zones),
            chanceFormat.chartSummary('snow_total', then, 2, 5, zones),
            countdown === null
              ? 'Riverside usually announces'
              : `Riverside usually announces ${countdown}`,
          );
          outputs.push(chanceFormat.announcesKey(then, zones, morning));
          const moved = chanceFormat.moved({
            previous: 0.3,
            current: 0.2,
            at: evening,
            now: then,
            zones,
          });
          if (moved !== null) outputs.push(moved);
        }
      }
      for (let percent = 0; percent <= 100; percent++) {
        const chance = percent / 100;
        outputs.push(chanceFormat.chanceOn('2026-01-13'), chanceFormat.howWeGot(chance));
        outputs.push(chanceFormat.delayInstead(chance));
        outputs.push(
          chanceFormat.baseReason(
            { kind: 'alert', points: percent, alert: 'extreme_cold_warning' },
            'Riverside',
          ),
          chanceFormat.baseReason({ kind: 'day_after', points: percent }, 'the district'),
          chanceFormat.baseReason({ kind: 'similar_days', points: percent }, 'the district'),
        );
        for (const scope of ['nearby', 'county', 'state', 'region'] as const) {
          outputs.push(
            chanceFormat.baseReason(
              { kind: 'pooled', points: percent, scope, alert: null },
              'the district',
            ),
            chanceFormat.baseReason(
              { kind: 'pooled', points: percent, scope, alert: 'winter_storm_warning' },
              'the district',
            ),
          );
        }
      }
      for (const status of ['closed', 'delayed', 'remote', 'earlyDismissal'] as const) {
        outputs.push(chanceFormat.neighborPosted('Riverside', status, '2026-01-16'));
        outputs.push(
          reason({ kind: 'neighbors', points: 2, names: ['Riverside'], count: 1, status }),
        );
        outputs.push(reason({ kind: 'neighbors', points: 2, names: null, count: 4, status }));
        outputs.push(
          reason({ kind: 'neighbors', points: 2, names: null, count: 4, status, said: true }),
          reason({ kind: 'neighbors', points: 2, names: null, count: 1, status, said: true }),
        );
      }
      for (let tenths = 0; tenths <= 240; tenths += 5) {
        const inches = tenths / 10;
        outputs.push(
          chanceFormat.inches(inches),
          chanceFormat.weatherEvent('snow_stopped', inches),
        );
        outputs.push(reason({ kind: 'icy_roads', points: 2, inches }));
        outputs.push(reason({ kind: 'ice', points: 2, inches }));
        outputs.push(
          reason({
            kind: 'snow_total',
            points: 5,
            low: inches,
            high: inches + 3,
            overnight: true,
            record,
          }),
        );
      }
      for (let degrees = -40; degrees <= 40; degrees++) {
        outputs.push(chanceFormat.degrees(degrees));
        outputs.push(reason({ kind: 'wind_chill', points: 2, feelsLike: degrees }));
        outputs.push(reason({ kind: 'cold', points: 2, feelsLike: degrees, day: '2026-01-15' }));
        outputs.push(
          reason({ kind: 'wind_chill', points: 2, feelsLike: degrees, said: true }),
          reason({ kind: 'cold', points: 2, feelsLike: degrees, day: '2026-01-15', said: true }),
        );
      }
      outputs.push(chanceFormat.district('300'));
      for (const points of [-100, -9, -1, 1, 9, 100]) outputs.push(chanceFormat.points(points));
      expect(allProblems(outputs)).toEqual([]);
      // No hedge in any of it: a forecast is the forecast's claim.
      expect(
        outputs.filter((text) => /\b(should|could|around|about|might|may)\b/u.test(text)),
      ).toEqual([]);
      // One minus sign.
      expect(outputs.filter((text) => /(^|\s)-\d/u.test(text))).toEqual([]);
    });
  });

  describe('replays and alerts', () => {
    it('writes a replay moment and speed', () => {
      expect(format.replayMoment(at('2026-01-12T11:00:00Z'), nyc)).toBe(
        `Mon, Jan 12 · 6:00${NBSP}AM`,
      );
      expect(format.speed(4)).toBe('4×');
      expect(format.speed(0.5)).toBe('0.5×');
      expect(format.speed(0.1 + 0.2)).toBe('0.3×');
      expect(format.speed(0.005)).toBe('0.01×');
      expect(format.speed(1000)).toBe('1,000×');
      expect(format.speed(1e21)).toBe('1,000,000,000,000,000,000,000×');
      // Never "0×": a speed that rounds to nothing is refused.
      for (const bad of [0, 0.001, 0.0049, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
        expect(() => format.speed(bad)).toThrow(RangeError);
      }
    });

    it('names an alert by hazard and level', () => {
      expect(format.alert('winter', 'warning')).toBe('Winter weather warning');
      expect(format.alert('flood', 'watch')).toBe('Flood watch');
      expect(format.alert('heat', 'advisory')).toBe('Heat advisory');
    });

    it('refuses a key that names no string, so "undefined" never shows', () => {
      const bogus = 'toString' as StatusKey;
      expect(() => format.count(bogus, 1)).toThrow(RangeError);
      expect(() => format.count('open' as StatusKey, 1)).toThrow(RangeError);
      expect(() => format.summary({ ['open' as StatusKey]: 1 })).not.toThrow();
      expect(() => format.statusOn(bogus, '2026-01-12', at('2026-01-12T12:00:00Z'), nyc)).toThrow(
        RangeError,
      );
      expect(() => format.alert('snow' as HazardKey, 'warning')).toThrow(RangeError);
      expect(() => format.alert('winter', 'alarm' as AlertLevelKey)).toThrow(RangeError);
    });
  });

  describe('output follows the house style', () => {
    const statuses = Object.keys(copy.status) as StatusKey[];
    const hazards = Object.keys(copy.hazard) as HazardKey[];
    const levels = Object.keys(copy.alertLevel) as AlertLevelKey[];
    const days = [...calendarDays('2026-01-01', 365), ...calendarDays('2028-01-01', 366)];

    it('for counts and plurals', () => {
      const outputs = COUNTS.flatMap((n) => [
        format.number(n),
        format.schools(n),
        format.results(n),
        ...statuses.map((status) => format.count(status, n)),
        format.summary(Object.fromEntries(statuses.map((status) => [status, n]))),
        format.outOf(Math.floor(n / 3), n),
      ]);
      expect(allProblems(outputs)).toEqual([]);
    });

    it('for every time of day in every US time zone through a year', () => {
      const instants = instantsThrough(2026, 37);
      const now = new Date(Date.UTC(2026, 6, 1));
      const outputs: string[] = [];
      for (const zone of ZONES) {
        for (const instant of instants) {
          outputs.push(format.liveAt(instant, zone), format.replayMoment(instant, zone));
        }
        for (const instant of instants.filter((_, i) => i % 97 === 0)) {
          outputs.push(
            format.updatedAt(instant, zone, now),
            format.offline(instant, zone, now),
            format.posted(instant, zone, now),
          );
        }
      }
      for (let minute = 0; minute < 1440; minute += 1) outputs.push(format.clock(minute));
      expect(allProblems(outputs)).toEqual([]);
    });

    it('for every day of a year and a leap year', () => {
      const now = new Date(Date.UTC(2026, 0, 1, 12));
      const outputs = days.flatMap((day) => [
        format.day(day),
        format.dayWithYear(day),
        format.through(day),
        format.span('2025-12-01', day),
        format.span(day, '2028-12-31'),
        ...statuses.map((status) => format.statusOn(status, day, now, 'America/Denver')),
      ]);
      outputs.push(format.season('2025-2026'), format.season('2099-2100'));
      expect(allProblems(outputs)).toEqual([]);
    });

    it('for every delay and dismissal length', () => {
      const outputs: (string | null)[] = [];
      for (let shift = 1; shift <= 720; shift += 1) {
        outputs.push(
          format.delay(shift, null),
          format.dismissal(shift, null),
          format.delay(shift, (shift * 7) % 1440),
          format.dismissal(shift, (shift * 11) % 1440),
        );
      }
      for (let minute = 0; minute < 1440; minute += 5) {
        outputs.push(format.delay(null, minute), format.dismissal(null, minute));
      }
      expect(allProblems(outputs)).toEqual([]);
    });

    it('for every grade span and a phone number', () => {
      const codes = ['PK', 'TK', 'KG', '01', '02', '03', '04', '05', '06', '07', '08', '09'];
      codes.push('10', '11', '12', '13');
      const outputs = codes.flatMap((low, i) =>
        codes.slice(i).map((high) => format.grades(low, high)),
      );
      outputs.push(format.phone('8169361230'));
      for (let metres = 0; metres < 40_000; metres += 97) outputs.push(format.miles(metres));
      expect(allProblems(outputs)).toEqual([]);
    });

    it('for chances, bins, leads, speeds and alerts', () => {
      const outputs: string[] = [];
      for (let i = 0; i <= 1000; i += 1) outputs.push(format.chance(i / 1000));
      for (let low = 0; low < 100; low += 10) outputs.push(format.percentRange(low, low + 10));
      outputs.push(format.lead(0), format.lead(1), format.lead(2));
      outputs.push(...[0.01, 0.25, 0.5, 1, 1.5, 2, 4, 8, 16, 1000, 12_345.678].map(format.speed));
      for (const hazard of hazards)
        for (const level of levels) outputs.push(format.alert(hazard, level));
      expect(allProblems(outputs)).toEqual([]);
    });
  });
});

describe('check-copy lint', () => {
  const roots: string[] = [];
  afterAll(() => {
    for (const root of roots) rmSync(root, { recursive: true, force: true });
  });

  /** Writes a throwaway web project and returns its root. */
  function project(files: Record<string, string>): string {
    const root = mkdtempSync(path.join(tmpdir(), 'snowlight-copy-lint-'));
    roots.push(root);
    for (const [name, content] of Object.entries(files)) {
      const file = path.join(root, name);
      mkdirSync(path.dirname(file), { recursive: true });
      writeFileSync(file, content);
    }
    return root;
  }

  /** [file, text the finding points at, part of its message]. */
  type Expected = [file: string, at: string, fragment: string];

  /**
   * Lints a fixture and compares its findings with the expected ones, each
   * placed on the line where its `at` text first appears in that file.
   */
  async function expectFindings(
    files: Record<string, string>,
    expected: Expected[],
  ): Promise<Finding[]> {
    const { findings } = await lintProject({ root: project(files) });
    const seen = findings.map(({ file, line, message }) => `${file}:${String(line)} ${message}`);
    const wanted = expected.map(([file, at, fragment]) => {
      const lines = (files[file] ?? '').split('\n');
      const line = lines.findIndex((text) => text.includes(at)) + 1;
      if (line === 0) throw new Error(`${at} is not in ${file}`);
      return { prefix: `${file}:${String(line)} `, fragment };
    });
    const matches = (entry: string, want: { prefix: string; fragment: string }): boolean =>
      entry.startsWith(want.prefix) && entry.includes(want.fragment);
    const missing = wanted
      .filter((want) => !seen.some((entry) => matches(entry, want)))
      .map((want) => `${want.prefix}… ${want.fragment}`);
    const unexpected = seen.filter((entry) => !wanted.some((want) => matches(entry, want)));
    expect({ missing, unexpected }).toEqual({ missing: [], unexpected: [] });
    expect(findings).toHaveLength(expected.length);
    return findings;
  }

  const cleanCopy = `export const copy = {
  appName: 'Snowlight',
  meta: { description: 'Schools on one map.' },
  search: { placeholder: 'Search a school, city, or ZIP', label: 'Search' },
  status: { closed: 'Closed', delayed: 'Delayed' },
  manifest: { name: 'Snowlight', shortName: 'Snowlight', description: 'Schools on one map.' },
};
export const format = {
  count: (status: 'closed' | 'delayed', n: number): string => \`\${copy.status[status]} \${String(n)}\`,
  schools: (n: number): string => String(n),
};
export const STATUS_KEYS = ['closed', 'delayed'] as const;
export const DOT = ' · ';
`;
  const cleanIndex = `<!doctype html>
<html lang="en">
  <head>
    <title>%copy.appName%</title>
    <meta name="description" content="%copy.meta.description%" />
    <meta property="og:title" content="%copy.appName%" />
    <script type="application/ld+json">{ "@type": "WebSite", "name": "%copy.appName%" }</script>
    <style>body { background: #000; } li::before { content: '\\2022'; }</style>
  </head>
  <body>
    <h1>%copy.appName%</h1>
    <input placeholder="%copy.search.placeholder%" aria-label="%copy.search.label%" />
    <script>document.title = document.title || '';</script>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
`;
  const cleanManifest = JSON.stringify({
    name: 'Snowlight',
    short_name: 'Snowlight',
    description: 'Schools on one map.',
  });

  it('passes a project that takes all its text from copy.ts', async () => {
    const root = project({
      'src/copy.ts': cleanCopy,
      'src/Good.svelte': `<script lang="ts">
  import { copy, format } from './copy';
  import Badge from './Badge.svelte';
  let { school, n, query = '' }: { school: { name: string; city: string; state: string }; n: number; query?: string } = $props();
  const kinds = ['closed', 'delayed'] as const;
  const counts = { closed: 3, delayed: 1 };
  const legend = kinds.map((kind) => ({ kind, label: copy.status[kind], color: '#7FD4FF' }));
  const Icon = 'svg';
  const icon = '<svg viewBox="0 0 1 1"><path d="M0 0h1" /></svg>';
  const statusName = (kind: 'closed' | 'delayed'): string => copy.status[kind];
  let state = $state({ mode: 'idle' });
  function busy(): void { state.mode = 'loading'; }
  console.warn('Snowlight: debug only');
</script>

<h2 class="title">{school.name}</h2>
<p>{school.city}, {school.state} · {format.count('closed', n)}</p>
<input type="search" value={query} placeholder={copy.search.placeholder} aria-label={copy.search.label} />
<input type="hidden" name="kind" value="closed" />
<button class="close" data-kind="closed" title={copy.search.label} onclick={busy}>×</button>
{#each kinds as kind (kind)}<span>{copy.search[kind === 'closed' ? 'label' : 'placeholder']}</span>{/each}
{#each Object.entries(counts) as [kind, count] (kind)}<span data-kind={kind}>{count}</span>{/each}
{#each legend as item (item.kind)}<li class="glyph {item.kind}" style="--c: {item.color}">{item.label}</li>{/each}
{#snippet badge(kind: 'closed' | 'delayed')}<b>{copy.status[kind]}</b>{/snippet}
{@render badge('closed')}
<span>{statusName('delayed')}</span>
<Badge status="closed" variant="quiet" />
<span class={['a', state.mode === 'loading' && 'b']} aria-hidden="true">{n} / {n}</span>
<span>{String(n)}%</span>
<svg aria-hidden="true"><path d="M0 0h1" /></svg>
{@html icon}
<span>&nbsp;&middot;&nbsp;</span>
{#if n > 0}<b>{format.schools(n)}</b>{/if}
<svelte:element this={Icon} />
<img alt="" src="x.png" />

<style>
  .title { color: #f5f5f5; }
  .title::after { content: ''; }
</style>
`,
      'src/Badge.svelte': `<script lang="ts">
  import { copy } from './copy';
  let { status, variant }: { status: 'closed' | 'delayed'; variant: string } = $props();
</script>
<span class={variant}>{copy.status[status]}</span>
`,
      'src/dom.ts': `import { copy } from './copy';
export function mark(el: HTMLElement, label: string, n: number): void {
  el.setAttribute('class', 'glow');
  el.dataset.kind = 'closed';
  el.className = 'glow closed';
  el.title = label;
  el.textContent = \`\${copy.status.closed} · \${String(n)}\`;
  el.append(copy.appName, ' · ', String(n));
  const params = new URLSearchParams();
  params.append('q', 'closed schools');
  const append = (part: string): string => part;
  append('not the DOM');
  const state = { value: 'loading' };
  state.value = 'ready';
  // A field of the project's own object named like a DOM property is not a DOM write.
  const record = { title: '' };
  record.title = 'Kept for sorting';
  void record;
  if (n < 0) throw new Error('Snowlight: n must not be negative');
}
mark(document.body, copy.search.label, 3);
`,
      // Methods, keys, errors, packages and forms used the way they should be.
      'src/Methods.svelte': `<script lang="ts">
  import { fade } from 'svelte/transition';
  import { copy, DOT, format, STATUS_KEYS } from './copy';
  let { minutes, rows, name }: { minutes: number; rows: string[]; name: string } = $props();
  const loaded = fetch('/x').then((response) => response.json()).catch(() => copy.appName);
  const params = new URLSearchParams(location.search);
  async function share(): Promise<void> {
    try {
      await navigator.clipboard.writeText(\`\${location.origin}/?s=\${name}\`);
    } catch {
      document.title = copy.appName;
    }
  }
</script>
<p transition:fade>{String(minutes).padStart(2, '0')}</p>
<p>{copy.status.closed.replace('{n}', String(minutes))}{name.replace(/\\s+/gu, ' ')}{name.replace(/(\\d+)/u, '$1')}</p>
<p>{rows.join(' · ')}{rows.map((row) => row.trim()).join(', ')}{format.schools(minutes)}{rows.join(DOT)}</p>
{#each STATUS_KEYS as key (key)}<i class={key} data-kind={key}>{copy.status[key]}</i>{/each}
{#each Object.entries(copy.status) as [key, label] (key)}<i data-kind={key}>{label}</i>{/each}
<p>{copy.status.closed.trim()}{params.get('q') ?? ''}{minutes.toLocaleString('en-US', { notation: 'compact' })}</p>
{#await loaded then value}<b>{value.name}</b>{:catch}<b>{copy.appName}</b>{/await}
<form><input type="submit" value={copy.search.label} /><button onclick={share}>{copy.appName}</button></form>
<details><summary>{copy.appName}</summary><p>{name}</p></details>
`,
      'src/styles.css': `li::before { content: '\\2022'; }\n.x::after { content: ""; }\n`,
      'index.html': cleanIndex,
      'public/site.webmanifest': cleanManifest,
    });
    const { findings, scanned } = await lintProject({ root });
    expect(findings).toEqual([]);
    expect(scanned).toMatchObject({ svelte: 3, scripts: 1, styles: 1, html: 1, manifests: 1 });
  }, 30_000);

  it('reads the copy modules that load later as part of copy.ts, and no other module', async () => {
    await expectFindings(
      {
        'src/copy.ts': cleanCopy,
        'src/copy-chance.ts': `import { copy } from './copy.ts';
export const chanceFormat = {
  canceled: (name: string): string => \`\${name} canceled \${copy.status.closed}\`,
};
`,
        'src/words.ts': `export const words = { canceled: (name: string): string => \`\${name} canceled\` };
`,
        'src/Moment.svelte': `<script lang="ts">
  import { chanceFormat } from './copy-chance';
  import { words } from './words';
  let { name }: { name: string } = $props();
</script>
<p>{chanceFormat.canceled(name)}</p>
<p>{words.canceled(name)}</p>
`,
      },
      [['src/words.ts', 'canceled`', 'literal text "canceled" in <p> at src/Moment.svelte']],
    );
  });

  it('reads the formatters’ module as part of copy.ts, and no other module like it', async () => {
    await expectFindings(
      {
        'src/copy.ts': `export const copy = { status: { closed: 'Closed' } };
`,
        'src/copy-format.ts': `import { copy } from './copy.ts';
export const format = {
  closedAt: (name: string): string => \`\${name} \${copy.status.closed}\`,
};
`,
        'src/words.ts': `export const words = { closed: (name: string): string => \`\${name} closed\` };
`,
        'src/Moment.svelte': `<script lang="ts">
  import { format } from './copy-format';
  import { words } from './words';
  let { name }: { name: string } = $props();
</script>
<p>{format.closedAt(name)}</p>
<p>{words.closed(name)}</p>
`,
      },
      [['src/words.ts', 'closed`', 'literal text "closed" in <p> at src/Moment.svelte']],
    );
  });

  it('follows a copy module loaded with import(), through Promise.all, then and assignments', async () => {
    const later = `import { copy } from './copy.ts';
export const format = {
  number: (n: number): string => String(n),
  closed: (): string => copy.status.closed,
};
`;
    // As App.svelte might take the formatters: a promise of the module among others, a later
    // assignment to state, a then, and an await.
    const key = `<script lang="ts">
  let { count }: { count: number } = $props();
  let format = $state.raw<{ number: (n: number) => string } | null>(null);
  void Promise.all([Promise.resolve(1), import('./copy-format')]).then(([, formatters]) => {
    format = formatters.format;
  });
  const closed = import('./copy-format').then((module) => module.format.closed());
  async function words(): Promise<string> {
    const { format: loaded } = await import('./copy-format');
    return loaded.closed();
  }
</script>
{#if format !== null}
  <p class="upper">{format.number(count).toUpperCase()}</p>
  <p class="cut">{format.number(count).slice(0, 1)}</p>
  <p class="keys">{Object.keys(format).join()}</p>
{/if}
{#await closed then text}<b>{text}</b>{/await}
{#await words() then text}<i>{text}</i>{/await}
`;
    await expectFindings(
      {
        'src/copy.ts': `export const copy = { status: { closed: 'Closed' } };
`,
        'src/copy-format.ts': later,
        'src/Key.svelte': key,
      },
      [
        ['src/Key.svelte', '<p class="upper">', 'copy text put through toUpperCase() in <p>'],
        ['src/Key.svelte', '<p class="cut">', 'copy text put through slice() in <p>'],
        ['src/Key.svelte', '<p class="keys">', 'the copy key "number" in <p>'],
        ['src/Key.svelte', '<p class="keys">', 'the copy key "closed" in <p>'],
      ],
    );
  });

  it('reports an export of a later copy module named like one of copy.ts', async () => {
    await expectFindings(
      {
        'src/copy.ts': `export const copy = { status: { closed: 'Closed' } };
export const format = { closed: (): string => copy.status.closed };
`,
        'src/copy-format.ts': `export const format = { open: (): string => 'Open' };
`,
      },
      [
        [
          'src/copy-format.ts',
          'export const format',
          'export format is also an export of src/copy.ts; rename one of them',
        ],
      ],
    );
  });

  it('finds literal text in components, DOM writes, index.html and manifests', async () => {
    const bad = `<script lang="ts">
  import { copy } from './copy';
  import Tooltip from './Tooltip.svelte';
  let open = $state(false);
  const heading = 'Closed schools';
  let label = $derived(open ? 'Close' : copy.appName);
  const LABELS = { back: 'Back' };
  let n = 3;
  const items = [{ label: 'Listed item' }, { label: copy.appName }];
  function snowDay(): string { return 'Snow day'; }
  const obj = { nested: { text: 'Nested text' } };
</script>

<svelte:head><title>Snowlight</title></svelte:head>
<h2>{heading}</h2>
<p>Closed today</p>
<input placeholder="Search" aria-label={label} />
<img alt="Map" src="x.png" />
<button title={\`\${n} schools\`}>{LABELS.back}</button>
<span>{n > 1 ? 'Many schools' : 'One school'}</span>
<span>{open && 'Open'}</span>
{#if open}<em>Remote</em>{:else}<em>{copy.appName}</em>{/if}
{#each [1] as item (item)}{@const note = 'Note'}<i>{note}{item}</i>{/each}
<Tooltip text="Hello" />
<input type="submit" value="Go" />
<span>→</span>
{@html '<b>Bold</b>'}
{#each items as item (item.label)}<li>{item.label}</li>{/each}
{#snippet row(text: string)}<b>{text}</b>{/snippet}
{@render row('Rendered text')}
<p>{snowDay()}</p>
<p>{obj.nested.text}</p>
<div {...{ 'aria-label': 'Spread label' }}></div>
<p>{String('Wrapped')}</p>
`;
    const dom = `const forText = 'Const message';
const forNode = 'Node message';
const forLabel = 'Label message';
const shared = 'Shared message';
export function paint(el: HTMLElement, n: number): void {
  el.textContent = 'Closed';
  el.setAttribute('aria-label', \`\${String(n)} schools\`);
  el.setAttribute('class', 'glow');
  el.title = n > 1 ? 'Many' : '';
  document.title = 'Snowlight';
  alert('Done');
  el.innerText = forText;
  el.append('Appended text');
  el.replaceChildren('Replaced');
  el.appendChild(document.createTextNode(forNode));
  el.setAttribute('aria-label', forLabel);
  el.textContent = shared;
  el.appendChild(document.createTextNode(shared));
  el.setAttribute('aria-label', shared);
}
`;
    const index = `<!doctype html>
<html lang="en">
  <head>
    <title>%copy.appName%</title>
    <meta name="description" content="%copy.meta.description%" />
    <meta property="og:title" content="%copy.bad.hedge%" />
    <meta name="twitter:title" content="Snowlight Beta" />
  </head>
  <body><h1>%copy.appName%</h1><p>Loading</p></body>
</html>
`;
    const vite = `import { VitePWA } from 'vite-plugin-pwa';
import { copy } from './src/copy';
export default { plugins: [VitePWA({ manifest: { name: 'Snowlight Beta', short_name: \`\${copy.appName} Live\`, description: copy.meta.description } })] };
`;
    const manifest = JSON.stringify({ name: 'Snowlight', description: 'Powered by AI!' });
    await expectFindings(
      {
        'src/copy.ts': `export const copy = {
  appName: 'Snowlight',
  meta: { description: 'Schools on one map.' },
  bad: { hedge: 'Closures may happen' },
};
`,
        'src/Bad.svelte': bad,
        'src/dom.ts': dom,
        'src/dom.test.ts': `document.body.textContent = 'Fixture text in a test is fine';\n`,
        'index.html': index,
        'public/manifest.webmanifest': manifest,
        'vite.config.ts': vite,
      },
      [
        ['src/copy.ts', 'export const copy', 'banned phrase "may" in copy.bad.hedge'],
        // A literal is reported where it is written, with where it shows.
        ['src/Bad.svelte', "'Closed schools'", '"Closed schools" in <h2> at src/Bad.svelte:15'],
        ['src/Bad.svelte', "'Close'", '"Close" in aria-label="…" on <input> at src/Bad.svelte:17'],
        ['src/Bad.svelte', "'Back'", '"Back" in <button> at src/Bad.svelte:19'],
        ['src/Bad.svelte', '<title>Snowlight', '"Snowlight" in <title>'],
        ['src/Bad.svelte', '<p>Closed today', '"Closed today" in <p>'],
        ['src/Bad.svelte', 'placeholder="Search"', '"Search" in placeholder="…" on <input>'],
        ['src/Bad.svelte', 'alt="Map"', '"Map" in alt="…" on <img>'],
        ['src/Bad.svelte', 'title={`', '"schools" in title="…" on <button>'],
        ['src/Bad.svelte', "'Many schools'", '"Many schools" in <span>'],
        ['src/Bad.svelte', "'One school'", '"One school" in <span>'],
        ['src/Bad.svelte', "'Open'", '"Open" in <span>'],
        ['src/Bad.svelte', '<em>Remote', '"Remote" in <em>'],
        ['src/Bad.svelte', "'Note'", '"Note" in <i>'],
        ['src/Bad.svelte', 'text="Hello"', '"Hello" in text="…" on <Tooltip>'],
        ['src/Bad.svelte', 'value="Go"', '"Go" in value="…" on <input>'],
        ['src/Bad.svelte', '<span>→', '"→" in <span>'],
        ['src/Bad.svelte', '<b>Bold', '"Bold" in the markup'],
        // {#each} over an array of object literals, read through the item.
        ['src/Bad.svelte', "'Listed item'", '"Listed item" in <li> at src/Bad.svelte:28'],
        // A snippet's parameter, filled by {@render}.
        ['src/Bad.svelte', "row('Rendered text')", '"Rendered text" in <b> at src/Bad.svelte:29'],
        // The return value of a function of the component.
        ['src/Bad.svelte', "'Snow day'", '"Snow day" in <p> at src/Bad.svelte:31'],
        // A chain of members.
        ['src/Bad.svelte', "'Nested text'", '"Nested text" in <p> at src/Bad.svelte:32'],
        // A spread attribute.
        ['src/Bad.svelte', "'Spread label'", '"Spread label" in a spread on <div>'],
        // A string passed through String().
        ['src/Bad.svelte', "'Wrapped'", '"Wrapped" in <p>'],
        ['src/dom.ts', "'Closed'", '"Closed" written to .textContent'],
        ['src/dom.ts', 'schools`', '"schools" written to the aria-label attribute'],
        ['src/dom.ts', "'Many'", '"Many" written to .title'],
        ['src/dom.ts', "= 'Snowlight'", '"Snowlight" written to .title'],
        ['src/dom.ts', "'Done'", '"Done" written to alert()'],
        // A constant written to the DOM, and the DOM's insert methods.
        ['src/dom.ts', "'Const message'", '"Const message" written to .innerText at src/dom.ts:12'],
        ['src/dom.ts', "'Appended text'", '"Appended text" written to append()'],
        ['src/dom.ts', "'Replaced'", '"Replaced" written to replaceChildren()'],
        [
          'src/dom.ts',
          "'Node message'",
          '"Node message" written to createTextNode() at src/dom.ts:15',
        ],
        [
          'src/dom.ts',
          "'Label message'",
          '"Label message" written to the aria-label attribute at src/dom.ts:16',
        ],
        // One literal shown in three places: one finding that counts them.
        [
          'src/dom.ts',
          "'Shared message'",
          '"Shared message" written to .textContent at src/dom.ts:17, and 2 more places;',
        ],
        ['index.html', 'og:title', 'banned phrase "may" in content="…" on <meta>'],
        ['index.html', 'twitter:title', 'literal text "Snowlight Beta"'],
        ['index.html', 'twitter:title', 'banned phrase "beta"'],
        ['index.html', 'twitter:title', 'Title Case "Beta"'],
        ['index.html', '<p>Loading', 'literal text "Loading"'],
        ['public/manifest.webmanifest', 'Powered', 'banned phrase "powered by" in description'],
        ['public/manifest.webmanifest', 'Powered', 'banned phrase "AI" in description'],
        ['public/manifest.webmanifest', 'Powered', 'all caps "AI" in description'],
        ['public/manifest.webmanifest', 'Powered', 'exclamation mark in description'],
        ['public/manifest.webmanifest', 'Powered', 'description "Powered by AI!" is not a string'],
        ['vite.config.ts', 'Snowlight Beta', '"Snowlight Beta" in manifest name'],
        ['vite.config.ts', ' Live`', '"Live" in manifest short_name'],
      ],
    );
  }, 30_000);

  it('follows what a method’s arguments add, whatever the method is called on', async () => {
    // A prop, copy, a formatter's output and fetched data are all receivers the
    // lint cannot see into; the literals handed to their methods still show.
    const receivers = `<script lang="ts">
  import { writable } from 'svelte/store';
  import { copy, format } from './copy';
  let { name, n }: { name: string; n: number } = $props();
  const rows = (await fetch('/rows.json').then((response) => response.json())) as { label: string }[];
  const labels = writable('');
  const tail = ' tail var';
  // A rune, even where a variable shares its name: not the store "derived".
  const derived = $derived.by(() => 'Rune text');
  function replacer(): string {
    return 'Named replacement';
  }
</script>
<p>{name.concat(' case one concat')}</p>
<p>{name.replace('x', 'Case one replace')}</p>
<p>{name.padEnd(20, 'Case one pad')}</p>
<p>{copy.status.closed.concat(' case two concat')}</p>
<p>{format.schools(n).replace('schools', 'Case two kids')}</p>
<input aria-label={copy.search.label.replace('Search', 'Case two find')} />
<p>{copy.status.delayed.padStart(12, 'Case two pad')}{copy.status.closed.replaceAll('C', 'Case two all')}</p>
<p>{name.concat(...[' spread arg'])}{name.concat(tail)}{name?.concat(' optional')}</p>
<p>{name.replace(/x/gu, () => 'Callback replacement')}{name.replace(/x/gu, replacer)}</p>
<p>{String(n).concat(' number')}{\`\${name}\`.padStart(9, 'Template pad')}{$labels.concat(' store')}</p>
<p>{rows.map((row) => row.label).join(' and more ')}</p>
<p>{rows.map((row) => \`\${row.label} mapped\`).join()}{rows.flatMap((row) => [row.label, 'Flat extra']).join()}</p>
<p>{rows.reduce((all, row) => all + row.label, 'Reduce seed')}</p>
<p>{rows.with(0, { label: 'With item' }).map((row) => row.label).join()}{rows.toSpliced(0, 0, { label: 'Spliced item' }).map((row) => row.label).join()}</p>
<p>{Array(2).fill('Filled').join()}{Array.from(rows, (row) => \`\${row.label} kids\`).join()}</p>
{#each rows.concat([{ label: 'Extra option' }]) as row (row.label)}<li>{row.label}</li>{/each}
<p>{derived}</p>
<p>{String(n).padStart(2, '0')}{name.replace(/(\\d+)/u, '$1')}{copy.status.closed.replace('{n}', String(n))}{rows.join(' · ')}</p>
`;
    const dom = `import { copy } from './copy';
export function label(element: HTMLElement, name: string): void {
  element.textContent = name.concat(' dom');
  document.title = copy.appName.concat(' live');
  element.setAttribute('aria-label', copy.search.label.padEnd(30, 'Padded label'));
  // Borrowed with call and apply.
  element.title = String.prototype.concat.call(name, ' borrowed');
  element.ariaLabel = Array.prototype.join.call([name], ' or ');
  element.textContent = ''.padEnd.apply(name, [9, 'Applied pad']);
}
`;
    await expectFindings(
      {
        'src/copy.ts': cleanCopy,
        'src/Receivers.svelte': receivers,
        'src/dom.ts': dom,
        // Items added to data the lint cannot see into show where the data shows.
        'src/Writes.svelte': `<script lang="ts">
  let { names, data }: { names: string[]; data: { heading: string; rows: { label: string }[] } } = $props();
  const fetched = (await fetch('/rows.json').then((response) => response.json())) as { label: string }[];
  names.push('Pushed name');
  data.heading = 'Overridden heading';
  data.rows.unshift({ label: 'First row' });
  fetched.splice(0, 0, { label: 'Spliced row' });
</script>
<p>{names.join(', ')}</p>
<h2>{data.heading}</h2>
{#each data.rows as row (row.label)}<li>{row.label}</li>{/each}
{#each fetched as row (row.label)}<li>{row.label}</li>{/each}
`,
      },
      [
        // Literals handed to methods of a prop, of copy and of a formatter's output.
        ['src/Receivers.svelte', "' case one concat'", '"case one concat" in <p>'],
        ['src/Receivers.svelte', "'Case one replace'", '"Case one replace" in <p>'],
        ['src/Receivers.svelte', "'Case one pad'", '"Case one pad" in <p>'],
        ['src/Receivers.svelte', "' case two concat'", '"case two concat" in <p>'],
        ['src/Receivers.svelte', "'Case two kids'", '"Case two kids" in <p>'],
        ['src/Receivers.svelte', "'Case two find'", '"Case two find" in aria-label="…" on <input>'],
        ['src/Receivers.svelte', "'Case two pad'", '"Case two pad" in <p>'],
        ['src/Receivers.svelte', "'Case two all'", '"Case two all" in <p>'],
        // Spread and named arguments, optional calls, callbacks, templates and stores.
        ['src/Receivers.svelte', "' spread arg'", '"spread arg" in <p>'],
        ['src/Receivers.svelte', "' tail var'", '"tail var" in <p> at src/Receivers.svelte:21'],
        ['src/Receivers.svelte', "' optional'", '"optional" in <p>'],
        ['src/Receivers.svelte', "'Callback replacement'", '"Callback replacement" in <p>'],
        ['src/Receivers.svelte', "'Named replacement'", 'in <p> at src/Receivers.svelte:22'],
        ['src/Receivers.svelte', "' number'", '"number" in <p>'],
        ['src/Receivers.svelte', "'Template pad'", '"Template pad" in <p>'],
        ['src/Receivers.svelte', "' store'", '"store" in <p>'],
        // Array methods on data: a separator, what callbacks return, added items.
        ['src/Receivers.svelte', "' and more '", '"and more" in <p>'],
        ['src/Receivers.svelte', 'mapped`', '"mapped" in <p>'],
        ['src/Receivers.svelte', "'Flat extra'", '"Flat extra" in <p>'],
        ['src/Receivers.svelte', "'Reduce seed'", '"Reduce seed" in <p>'],
        ['src/Receivers.svelte', "'With item'", '"With item" in <p>'],
        ['src/Receivers.svelte', "'Spliced item'", '"Spliced item" in <p>'],
        ['src/Receivers.svelte', "'Filled'", '"Filled" in <p>'],
        ['src/Receivers.svelte', 'kids`', '"kids" in <p>'],
        ['src/Receivers.svelte', "'Extra option'", '"Extra option" in <li>'],
        ['src/Receivers.svelte', "'Rune text'", '"Rune text" in <p>'],
        ['src/Writes.svelte', "'Pushed name'", '"Pushed name" in <p> at src/Writes.svelte:9'],
        ['src/Writes.svelte', "'Overridden heading'", 'in <h2> at src/Writes.svelte:10'],
        ['src/Writes.svelte', "'First row'", '"First row" in <li> at src/Writes.svelte:11'],
        ['src/Writes.svelte', "'Spliced row'", '"Spliced row" in <li> at src/Writes.svelte:12'],
        ['src/dom.ts', "' dom'", '"dom" written to .textContent'],
        ['src/dom.ts', "' live'", '"live" written to .title'],
        ['src/dom.ts', "'Padded label'", '"Padded label" written to the aria-label attribute'],
        ['src/dom.ts', "' borrowed'", '"borrowed" written to .title'],
        ['src/dom.ts', "' or '", '"or" written to .ariaLabel'],
        ['src/dom.ts', "'Applied pad'", '"Applied pad" written to .textContent'],
      ],
    );
  }, 30_000);

  it('reports caught errors, copy.ts keys and codes, and copy cut or recased, where they show', async () => {
    const errors = `<script lang="ts">
  import { copy } from './copy';
  let message = $state('');
  let reason = $state('');
  async function load(): Promise<string> {
    try {
      const response = await fetch('/x');
      if (!response.ok) throw new Error('Could not load');
      return await response.text();
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
      return copy.appName;
    }
  }
  const later = fetch('/y').then((response) => response.text()).catch(() => 'Fallback text');
  window.addEventListener('unhandledrejection', (event) => {
    reason = String(event.reason);
  });
</script>
<p class="message">{message}</p>
<p class="reason">{reason}</p>
{#await load() then text}<b>{text}</b>{:catch problem}<i>{problem.message}</i>{/await}
{#await later then value}<em>{value}</em>{/await}
<svelte:boundary>
  <p>{copy.appName}</p>
  {#snippet failed(error)}<p class="failed">{String(error)}</p>{/snippet}
</svelte:boundary>
`;
    const script = `export function wire(element: HTMLElement, pending: Promise<string>): void {
  pending.then(
    (value) => value,
    (error: Error) => {
      element.title = error.message;
    },
  );
  pending.catch(({ message }: Error) => {
    element.setAttribute('aria-label', message);
  });
  window.onerror = (message) => {
    element.textContent = String(message);
  };
}
`;
    const keys = `<script lang="ts">
  import { copy, format, STATUS_KEYS } from './copy';
  let { n }: { n: number } = $props();
  const names: string[] = [];
  for (const key in copy.status) names.push(key);
</script>
<ul>{#each Object.keys(copy.status) as key (key)}<li class="key">{key}</li>{/each}</ul>
<ul>{#each STATUS_KEYS as key (key)}<li class={key}>{copy.status[key]}</li><li class="code">{key}</li>{/each}</ul>
<p class="names">{names.join(', ')}</p>
<p class="upper">{copy.status.closed.toUpperCase()}</p>
<p class="cut">{format.schools(n).slice(0, 2)}{copy.search.label[0]}</p>
`;
    const caught = "a caught error's text (caught at";
    await expectFindings(
      {
        'src/copy.ts': cleanCopy,
        'src/Errors.svelte': errors,
        'src/errors.ts': script,
        'src/made.ts': `export class SearchUnavailableError extends Error {}
class Deeper extends SearchUnavailableError {}
export const failure = new Deeper('Search could not start');
`,
        'src/Made.svelte': `<script lang="ts">
  import { failure } from './made';
  const boom = new Error('Boom');
</script>
<p class="made">{failure.message}{String(boom)}</p>
`,
        'src/Keys.svelte': keys,
      },
      [
        // A catch clause, {:catch}, .catch(), then's second callback, a boundary
        // and error listeners: whatever the error says is not copy.
        ['src/Errors.svelte', '<p class="message">', `${caught} src/Errors.svelte:10) in <p>`],
        ['src/Errors.svelte', '<p class="reason">', `${caught} src/Errors.svelte:16) in <p>`],
        ['src/Errors.svelte', '{:catch problem}', `${caught} src/Errors.svelte:22) in <i>`],
        ['src/Errors.svelte', "'Fallback text'", '"Fallback text" in <em>'],
        ['src/Errors.svelte', '<p class="failed">', `${caught} src/Errors.svelte:24) in <p>`],
        ['src/errors.ts', 'element.title', `${caught} src/errors.ts:2) written to .title`],
        ['src/errors.ts', "'aria-label'", `${caught} src/errors.ts:8) written to the aria-label`],
        ['src/errors.ts', 'element.textContent', `${caught} src/errors.ts:11) written to`],
        // An error made in code and shown says what the code wrote.
        ['src/Made.svelte', '<p class="made">', "an error's text (made at src/made.ts:3) in <p>"],
        [
          'src/Made.svelte',
          '<p class="made">',
          "an error's text (made at src/Made.svelte:3) in <p>",
        ],
        // Keys and codes of copy.ts name text; they are not text.
        ['src/Keys.svelte', '<li class="key">', 'the copy key "closed" in <li>'],
        ['src/Keys.svelte', '<li class="key">', 'the copy key "delayed" in <li>'],
        ['src/Keys.svelte', '<li class="code">', 'the copy code "closed" in <li>'],
        ['src/Keys.svelte', '<li class="code">', 'the copy code "delayed" in <li>'],
        ['src/Keys.svelte', '<p class="names">', 'the copy key "closed" in <p>'],
        ['src/Keys.svelte', '<p class="names">', 'the copy key "delayed" in <p>'],
        // Copy put through a method that changes it is no longer the copy.
        ['src/Keys.svelte', '<p class="upper">', 'copy text "Closed" put through toUpperCase()'],
        ['src/Keys.svelte', '<p class="cut">', 'copy text put through slice() in <p>'],
        ['src/Keys.svelte', '<p class="cut">', 'copy text "Search" cut by an index'],
      ],
    );
  }, 30_000);

  it('reads attributes shown by CSS attr(), text handed to packages, and other places text shows', async () => {
    const tip = `<script lang="ts">
  import { copy } from './copy';
  function mark(element: HTMLElement): void {
    element.dataset.hint = 'Dataset hint';
    element.setAttribute('data-tip', 'Set tip');
  }
</script>
<span class="tip" data-tip="Tip text" data-kind="closed" {@attach mark}>{copy.appName}</span>
<span class="hint" data-hint={copy.appName}></span>
<style>
  .tip::after { content: attr(data-tip); }
</style>
`;
    const packages = `<script lang="ts">
  import dayjs from 'dayjs';
  import upperFirst from 'lodash-es/upperFirst';
  import { fade } from 'svelte/transition';
  import { SvelteMap } from 'svelte/reactivity';
  import { copy } from './copy';
  let { when }: { when: Date } = $props();
  const labels = new SvelteMap([['closed', 'Reactive map text']]);
  const params = new URLSearchParams(location.search);
  const tag = (parts: TemplateStringsArray): string => parts.join('');
</script>
<p transition:fade={{ duration: 200 }}>{upperFirst('closed today')}</p>
<p>{dayjs(when).format('ddd MMM D')}{dayjs(when).format('YYYY-MM-DD')}</p>
<p>{labels.get('closed')}</p>
<p>{tag\`Tagged text\`}</p>
<p>{params.get('q') ?? copy.appName}{encodeURIComponent('a-b')}</p>
<p>{translate('Global helper text')}</p>
`;
    const places = `<script lang="ts">
  import { copy } from './copy';
  let { at, n }: { at: Date; n: number } = $props();
  const now = new Date();
  function speak(): void {
    speechSynthesis.speak(new SpeechSynthesisUtterance('Schools closed'));
    void navigator.clipboard.writeText('Copied words here');
    void navigator.clipboard.writeText(location.href);
    const meta = document.querySelector('meta[name=description]');
    if (meta instanceof HTMLMetaElement) meta.content = 'Meta words';
  }
</script>
<p class="now">{now}</p>
<p>{at.toDateString()}</p>
<p>{new Intl.NumberFormat('en-US', { style: 'unit', unit: 'day' }).format(n)}</p>
<p>{n.toLocaleString('en-US', { notation: 'compact', compactDisplay: 'long' })}</p>
<form><input type="submit" /><input type="reset" value={copy.appName} /><button onclick={speak}>{copy.appName}</button></form>
<details class="bare"><p>{copy.appName}</p></details>
<details><summary>{copy.appName}</summary></details>
<ul class="list"><li>{copy.appName}</li></ul>
<style>
  .list { list-style: 'Item: '; }
</style>
`;
    await expectFindings(
      {
        'src/copy.ts': cleanCopy,
        'src/Tip.svelte': tip,
        'src/theme.css': `.hint::after { content: ' ' attr(data-hint); }\n`,
        'src/Packages.svelte': packages,
        'src/Places.svelte': places,
      },
      [
        // attr() shows data-tip and data-hint, however they are set.
        ['src/Tip.svelte', 'data-tip="Tip text"', '"Tip text" in data-tip="…" on <span>'],
        ['src/Tip.svelte', "'Dataset hint'", '"Dataset hint" written to the data-hint attribute'],
        ['src/Tip.svelte', "'Set tip'", '"Set tip" written to the data-tip attribute'],
        // Text handed to a package or a global counts where it reads as words.
        ['src/Packages.svelte', "'closed today'", '"closed today" in <p>'],
        ['src/Packages.svelte', "'ddd MMM D'", '"ddd MMM D" in <p>'],
        ['src/Packages.svelte', "'Reactive map text'", 'in <p> at src/Packages.svelte:14'],
        ['src/Packages.svelte', 'Tagged text', '"Tagged text" in <p>'],
        ['src/Packages.svelte', "'Global helper text'", '"Global helper text" in <p>'],
        ['src/Places.svelte', "'Schools closed'", '"Schools closed" written to speech'],
        [
          'src/Places.svelte',
          "'Copied words here'",
          '"Copied words here" written to the clipboard',
        ],
        ['src/Places.svelte', "'Meta words'", '"Meta words" written to .content'],
        ['src/Places.svelte', '<p class="now">', 'a date written out by JavaScript'],
        [
          'src/Places.svelte',
          'toDateString',
          'toDateString() writes words outside the copy modules',
        ],
        [
          'src/Places.svelte',
          "style: 'unit'",
          'Intl.NumberFormat writes words outside the copy modules',
        ],
        [
          'src/Places.svelte',
          "compactDisplay: 'long'",
          'toLocaleString() writes words outside the copy modules',
        ],
        [
          'src/Places.svelte',
          'type="submit"',
          '<input type="submit"> without a value shows the browser',
        ],
        [
          'src/Places.svelte',
          '<details class="bare">',
          '<details> without a <summary> shows the browser',
        ],
        ['src/Places.svelte', "'Item: '", '"Item:" in CSS content in <style>'],
      ],
    );
  }, 30_000);

  it('follows text across files, component props, snippets, stores and classes', async () => {
    const files = {
      'src/copy.ts': cleanCopy,
      'src/lib/labels.ts': `export const LABELS = { closed: 'Imported label' };
export default function heading(): string { return 'Default export heading'; }
export enum Word { Snow = 'Enum word' }
`,
      'src/lib/index.ts': `export { LABELS as RELABELS } from './labels';\nexport * from './labels';\n`,
      'src/lib/data.json': '{ "title": "Json title", "list": ["Json item"] }\n',
      'src/lib/about.txt': 'Raw about text',
      'src/lib/store.svelte.ts': `import { writable } from 'svelte/store';
class Store {
  label = $state('Store field');
  get shout(): string { return 'Getter text'; }
  rename(): void { this.label = 'Method set'; }
}
export const store = new Store();
export const plain = writable('Store value');
plain.set('Store set value');
`,
      'src/lib/Legend.svelte': `<script lang="ts">
  let { items, heading2, note, row } = $props();
</script>
<ul>{#each items as item (item.label)}<li>{item.label}</li>{/each}</ul>
<h2>{heading2}</h2>
<p>{note}</p>
{@render row('Row text')}
`,
      'src/lib/Card.svelte': `<script lang="ts">let { title } = $props();</script>\n<h1>{title}</h1>\n`,
      'src/main.ts': `import { mount } from 'svelte';
import Card from './lib/Card.svelte';
mount(Card, { target: document.body, props: { title: 'Mounted title' } });
`,
      'src/App.svelte': `<script lang="ts">
  import { setContext } from 'svelte';
  import heading, { LABELS, Word } from './lib/labels';
  import * as L from './lib/labels';
  import { RELABELS } from './lib/index';
  import data from './lib/data.json';
  import about from './lib/about.txt?raw';
  import { store, plain } from './lib/store.svelte';
  import Legend from './lib/Legend.svelte';
  import Inner from './Inner.svelte';
  import Foreign from 'some-ui-kit';
  let msg = $state('');
  const lines: string[] = [];
  lines.push('Pushed line');
  const groups = [{ words: ['Nested each'] }];
  const obj = { get g() { return 'Object getter'; }, nested: { text: 'Optional chain' } };
  const KEY = 'k';
  const byKey = { [KEY]: 'Computed value' };
  const list = [{ label: 'Reduced' }];
  const LOOKUP: Record<string, string> = { closed: 'Looked up' };
  let { kind = 'closed', greeting = 'Default prop' } = $props();
  const map = new Map([['closed', 'Map value']]);
  class Box { label: string; constructor(label: string) { this.label = label; } }
  const box = new Box('Boxed text');
  const later = Promise.resolve('Then text').then((v) => v);
  let query = $state('Bound text');
  setContext('labels', { title: 'Context text' });
</script>

<p>{heading()}{LABELS.closed}{L.Word.Snow}{RELABELS.closed}</p>
<p>{data.title}{data.list[0]}{about}</p>
<p>{store.label}{store.shout}{$plain}</p>
<button onclick={() => (msg = 'Handler text')}>{msg}</button>
<p>{lines.join(' ')}</p>
{#each groups as g}{#each g.words as w}<b>{w}</b>{/each}{/each}
<p>{obj.g}{obj?.nested?.text}{byKey[KEY]}{LOOKUP[kind]}{greeting}{map.get(kind)}{box.label}</p>
<p>{list.reduce((acc, x) => acc + x.label, '')}</p>
{#await later then value}<i>{value}</i>{/await}
<input bind:value={query} />
<Legend items={[{ label: 'Legend item' }]} heading2="Prop heading" {...{ note: 'Spread prop' }}>
  {#snippet row(x: string)}<em>{x}</em>{/snippet}
</Legend>
<Foreign items={['Foreign item text']} variant="primary" timeZone="America/New_York" />
<Inner />
`,
      'src/Inner.svelte': `<script lang="ts">
  import { getContext } from 'svelte';
  const labels = getContext<{ title: string }>('labels');
</script>
<h3>{labels.title}{import.meta.env.VITE_SITE_NAME}</h3>
`,
      '.env': 'VITE_SITE_NAME="Env name"\nSECRET_TOKEN=not-shown\n',
    };
    await expectFindings(files, [
      ['src/lib/labels.ts', "'Imported label'", 'in <p> at src/App.svelte:30'],
      ['src/lib/labels.ts', "'Default export heading'", 'in <p> at src/App.svelte:30'],
      ['src/lib/labels.ts', "'Enum word'", 'in <p> at src/App.svelte:30'],
      ['src/lib/data.json', 'Json title', '"Json title" in <p> at src/App.svelte:31'],
      ['src/lib/data.json', 'Json item', '"Json item" in <p> at src/App.svelte:31'],
      ['src/lib/about.txt', 'Raw about text', '"Raw about text" in <p> at src/App.svelte:31'],
      ['src/lib/store.svelte.ts', "'Store field'", 'in <p> at src/App.svelte:32'],
      ['src/lib/store.svelte.ts', "'Getter text'", 'in <p> at src/App.svelte:32'],
      ['src/lib/store.svelte.ts', "'Method set'", 'in <p> at src/App.svelte:32'],
      ['src/lib/store.svelte.ts', "'Store value'", 'in <p> at src/App.svelte:32'],
      ['src/lib/store.svelte.ts', "'Store set value'", 'in <p> at src/App.svelte:32'],
      ['src/App.svelte', "'Handler text'", '"Handler text" in <button>'],
      ['src/App.svelte', "'Pushed line'", 'in <p> at src/App.svelte:34'],
      ['src/App.svelte', "'Nested each'", 'in <b> at src/App.svelte:35'],
      ['src/App.svelte', "'Object getter'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Optional chain'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Computed value'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Looked up'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Default prop'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Map value'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Boxed text'", 'in <p> at src/App.svelte:36'],
      ['src/App.svelte', "'Reduced'", 'in <p> at src/App.svelte:37'],
      ['src/App.svelte', "'Then text'", 'in <i> at src/App.svelte:38'],
      ['src/App.svelte', "'Bound text'", 'in bind:value="…" on <input> at src/App.svelte:39'],
      // Props given to a component of the project are checked where it shows them.
      ['src/App.svelte', "'Legend item'", 'in <li> at src/lib/Legend.svelte:4'],
      ['src/App.svelte', '"Prop heading"', 'in <h2> at src/lib/Legend.svelte:5'],
      ['src/App.svelte', "'Spread prop'", 'in <p> at src/lib/Legend.svelte:6'],
      ['src/lib/Legend.svelte', "'Row text'", 'in <em> at src/App.svelte:41'],
      ['src/main.ts', "'Mounted title'", 'in <h1> at src/lib/Card.svelte:2'],
      // A component from a package: words, but not keys, names or time zones.
      ['src/App.svelte', "'Foreign item text'", 'passed to items="…" on <Foreign>'],
      ['src/App.svelte', "'Context text'", 'in <h3> at src/Inner.svelte:5'],
      ['.env', 'VITE_SITE_NAME', '"Env name" in <h3> at src/Inner.svelte:5'],
    ]);
  }, 30_000);

  it('follows text from {#each} into snippets, and through spreads, nested components and legacy props', async () => {
    const files = {
      'src/copy.ts': cleanCopy,
      'src/Page.svelte': `<script lang="ts">
  import Row from './Row.svelte';
  import Middle from './Middle.svelte';
  import Legacy from './Legacy.svelte';
  const items = [{ label: 'Snippet item' }];
  const rows = [{ caption2: 'Spread row' }];
</script>
{#snippet line(item: { label: string })}<li>{item.label}</li>{/snippet}
{#each items as item (item.label)}{@render line(item)}{/each}
{#each rows as row (row.caption2)}<Row {...row} />{/each}
<Middle entries={[{ words: 'Two levels down' }]} />
<Legacy heading2="Legacy prop" />
`,
      'src/Row.svelte': `<script lang="ts">\n  let { caption2 } = $props();\n</script>\n<p>{caption2}</p>\n`,
      'src/Middle.svelte': `<script lang="ts">
  import Leaf from './Leaf.svelte';
  let { entries } = $props();
</script>
{#each entries as entry (entry.words)}<Leaf value={entry.words} />{/each}
`,
      'src/Leaf.svelte': `<script lang="ts">\n  let { value } = $props();\n</script>\n<b>{value}</b>\n`,
      'src/Legacy.svelte': `<script>\n  export let heading2 = 'Legacy default';\n</script>\n<h2>{heading2}</h2>\n`,
    };
    await expectFindings(files, [
      ['src/Page.svelte', "'Snippet item'", '"Snippet item" in <li> at src/Page.svelte:8'],
      ['src/Page.svelte', "'Spread row'", '"Spread row" in <p> at src/Row.svelte:4'],
      ['src/Page.svelte', "'Two levels down'", '"Two levels down" in <b> at src/Leaf.svelte:4'],
      ['src/Page.svelte', '"Legacy prop"', '"Legacy prop" in <h2> at src/Legacy.svelte:4'],
      ['src/Legacy.svelte', "'Legacy default'", '"Legacy default" in <h2> at src/Legacy.svelte:4'],
    ]);
  }, 30_000);

  it('finds text in CSS, inline scripts, JSON-LD, notifications, the share sheet and map labels', async () => {
    const files = {
      'src/copy.ts': cleanCopy,
      'src/Styled.svelte': `<div style:content={"'Directive text'"} style="content: 'Style attr'"></div>
<p class="x"></p>
<style>
  .x::after { content: 'After text'; }
</style>
`,
      'src/theme.css': `.y::before { content: "Sheet text"; }\n`,
      'src/sinks.ts': `import { copy } from './copy';
declare const maplibregl: { Popup: new () => { setText(t: string): void; setHTML(t: string): void } };
function show(message: string, el: HTMLElement): void { el.textContent = message; }
export function run(el: HTMLElement, map: { setLayoutProperty(a: string, b: string, c: unknown): void }): void {
  show('Shown via a parameter', el);
  [{ label: 'Each item' }].forEach((item) => { el.title = item.label; });
  void navigator.share({ title: 'Share title', text: 'Share text', url: '/x' });
  new Notification('Note title', { body: 'Note body' });
  const popup = new maplibregl.Popup();
  popup.setText('Popup text');
  popup.setHTML('<p>Popup html</p>');
  if (confirm('Sure about it')) window.alert(copy.appName);
  const layer = { layout: { 'text-field': 'Map text' } };
  const good = { layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']] } };
  const mixed = { layout: { 'text-field': ['concat', ['get', 'name'], ' campus'] } };
  map.setLayoutProperty('labels', 'text-field', ['get', 'name']);
  map.setLayoutProperty('labels', 'text-field', ['match', ['get', 'kind'], 'closed', 'Match out', 'Fallback out']);
  Object.assign(el, { textContent: 'Assigned text' });
  el.insertAdjacentHTML('beforeend', \`<span title="Html title">\${copy.appName}</span>\`);
  document.querySelector('meta')?.setAttribute('content', 'Meta via DOM');
  el.style.cssText = "content: 'Css text'";
  new CSSStyleSheet().insertRule(".q::after { content: 'Rule text' }");
  el.style.setProperty('content', "'Property text'");
  el.style.setProperty('color', 'rebeccapurple');
  void [layer, good, mixed];
}
`,
      'index.html': `<!doctype html>
<html lang="en">
  <head>
    <title>%copy.appName%</title>
    <script type="application/ld+json">{ "@type": "WebSite", "name": "Snowlight Live" }</script>
    <style>.z::before { content: 'Inline css'; }</style>
  </head>
  <body>
    <h1 style="content: 'Attr css'">%copy.appName%</h1>
    <script>document.title = 'Inline script';</script>
  </body>
</html>
`,
    };
    await expectFindings(files, [
      ['src/Styled.svelte', 'Directive text', '"Directive text" in style:content on <div>'],
      ['src/Styled.svelte', 'Style attr', '"Style attr" in style="…" on <div>'],
      ['src/Styled.svelte', 'After text', '"After text" in CSS content in <style>'],
      ['src/theme.css', 'Sheet text', '"Sheet text" in CSS content'],
      ['src/sinks.ts', "'Shown via a parameter'", 'written to .textContent at src/sinks.ts:3'],
      ['src/sinks.ts', "'Each item'", 'written to .title'],
      ['src/sinks.ts', "'Share title'", 'written to the share sheet'],
      ['src/sinks.ts', "'Share text'", 'written to the share sheet'],
      ['src/sinks.ts', "'Note title'", 'written to a notification'],
      ['src/sinks.ts', "'Note body'", 'written to a notification'],
      ['src/sinks.ts', "'Popup text'", 'written to setText()'],
      ['src/sinks.ts', 'Popup html', '"Popup html" written to setHTML()'],
      ['src/sinks.ts', "'Sure about it'", 'written to confirm()'],
      ['src/sinks.ts', "'Map text'", 'in a map label'],
      ['src/sinks.ts', "' campus'", '"campus" in a map label'],
      ['src/sinks.ts', "'Match out'", 'in a map label'],
      ['src/sinks.ts', "'Fallback out'", 'in a map label'],
      ['src/sinks.ts', "'Assigned text'", 'written to Object.assign()'],
      ['src/sinks.ts', 'Html title', '"Html title" written to insertAdjacentHTML()'],
      ['src/sinks.ts', "'Meta via DOM'", 'written to the content attribute'],
      ['src/sinks.ts', 'Css text', '"Css text" written to .cssText'],
      ['src/sinks.ts', 'Rule text', '"Rule text" written to insertRule()'],
      ['src/sinks.ts', 'Property text', '"Property text" written to setProperty()'],
      ['index.html', 'ld+json', 'literal text "Snowlight Live" in "name" in JSON-LD'],
      ['index.html', 'ld+json', 'Title Case "Live" in "name" in JSON-LD'],
      ['index.html', 'Inline css', '"Inline css" in CSS content in <style>'],
      ['index.html', 'Attr css', '"Attr css" in style="…" on <h1>'],
      ['index.html', "'Inline script'", '"Inline script" written to .title'],
    ]);
  }, 30_000);

  it('finds text handed to actions, bound into elements, or worded by Intl outside copy.ts', async () => {
    const files = {
      'src/copy.ts': cleanCopy,
      'src/tooltip.ts': `export function tooltip(node: HTMLElement, text: string): void {
  node.title = text;
}
`,
      'src/Acts.svelte': `<script lang="ts">
  import { tooltip } from './tooltip';
  import { copy } from './copy';
  let body = $state('Bound body');
  const key = 'textContent';
  const when = new Date();
  function stamp(el: HTMLElement): void {
    el[key] = 'Keyed write';
    el.dataset.at = when.toISOString();
  }
</script>
<button use:tooltip={'Action text'} {@attach stamp}>{copy.appName}</button>
<button use:tooltip={copy.search.label}>{copy.appName}</button>
<div contenteditable bind:textContent={body}></div>
<p>{when.toLocaleDateString('en-US')}</p>
<p>{new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric' }).format(when)}</p>
<p>{new Intl.DateTimeFormat('en-US', { month: '2-digit', day: '2-digit' }).format(when)}</p>
<p>{new Intl.RelativeTimeFormat('en-US').format(-1, 'day')}</p>
<p>{(1234).toLocaleString('en-US', { maximumFractionDigits: 0 })}</p>
`,
    };
    await expectFindings(files, [
      ['src/Acts.svelte', "'Action text'", '"Action text" written to .title at src/tooltip.ts:2'],
      ['src/Acts.svelte', "'Bound body'", '"Bound body" in bind:textContent'],
      ['src/Acts.svelte', "'Keyed write'", '"Keyed write" written to .textContent'],
      [
        'src/Acts.svelte',
        'toLocaleDateString',
        'toLocaleDateString() writes words outside the copy modules',
      ],
      [
        'src/Acts.svelte',
        "month: 'long'",
        'Intl.DateTimeFormat writes words outside the copy modules',
      ],
      [
        'src/Acts.svelte',
        'RelativeTimeFormat',
        'Intl.RelativeTimeFormat writes words outside the copy modules',
      ],
    ]);
  }, 30_000);

  it('stays quick and finite on self-reference, import cycles, recursion and long chains', async () => {
    const chain = Array.from(
      { length: 40 },
      (_, i) => `  const a${String(i + 1)} = a${String(i)} + a${String(i)};`,
    ).join('\n');
    const big = Array.from({ length: 20_000 }, (_, i) => `'w${String(i)}'`).join(', ');
    const aliases = Array.from(
      { length: 400 },
      (_, i) => `  const b${String(i + 1)} = b${String(i)};`,
    ).join('\n');
    const files = {
      'src/copy.ts': cleanCopy,
      'src/a.ts': `import { pong } from './b';\nexport function ping(): string { return pong(); }\nexport const A = 'From a';\n`,
      'src/b.ts': `import { ping, A } from './a';\nexport function pong(): string { return Math.random() > 0.5 ? ping() : A; }\n`,
      'src/Paths.svelte': `<script lang="ts">
  import { ping } from './a';
  const a0 = 'Chained';
${chain}
  let state = $state({ label: 'Self one' });
  state = { ...state, other: 'Self two' };
  let list = ['List one'];
  list = [...list, 'List two'];
  function rec(n: number): string { return n > 0 ? rec(n - 1) : 'Recursive'; }
  function even(n: number): string { return n === 0 ? 'Even' : odd(n - 1); }
  function odd(n: number): string { return n === 0 ? 'Odd' : even(n - 1); }
  const big = [${big}];
  const b0 = 'Too deep';
${aliases}
</script>
<p>{a40}</p>
<p>{state.label}{state.other}</p>
<p>{list.join()}</p>
<p>{rec(3)}{even(4)}</p>
<p>{big.length}</p>
<p>{ping()}</p>
<p>{b400}</p>
`,
    };
    const started = performance.now();
    await expectFindings(files, [
      ['src/Paths.svelte', "'Chained'", '"Chained" in <p>'],
      ['src/Paths.svelte', "'Self one'", '"Self one" in <p>'],
      ['src/Paths.svelte', "'Self two'", '"Self two" in <p>'],
      ['src/Paths.svelte', "'List one'", '"List one" in <p>'],
      ['src/Paths.svelte', "'List two'", '"List two" in <p>'],
      ['src/Paths.svelte', "'Recursive'", '"Recursive" in <p>'],
      ['src/Paths.svelte', "'Even'", '"Even" in <p>'],
      ['src/Paths.svelte', "'Odd'", '"Odd" in <p>'],
      ['src/a.ts', "'From a'", '"From a" in <p> at src/Paths.svelte:'],
      // Past the depth it follows, the lint says so rather than passing the text.
      [
        'src/Paths.svelte',
        '<p>{b400}',
        'text reaches <p> through more steps than the copy lint follows',
      ],
    ]);
    expect(performance.now() - started).toBeLessThan(10_000);
  }, 30_000);

  it('fails on a file it cannot read, rather than passing it unread', async () => {
    const { findings } = await lintProject({
      root: project({
        'src/copy.ts': cleanCopy,
        'src/Broken.svelte': '<p>{copy.appName</p>\n',
        'src/broken.ts': 'export const = 1;\n',
      }),
    });
    expect(findings.map(({ file, message }) => `${file} ${message.split(':')[0] ?? ''}`)).toEqual([
      'src/Broken.svelte cannot read this file, so its text cannot be checked',
      'src/broken.ts cannot read this file, so its text cannot be checked',
    ]);
  }, 30_000);

  it('ties manifests to copy.manifest', () => {
    const copyTree = {
      appName: 'Snowlight',
      manifest: { name: 'Snowlight', shortName: 'Snowlight', description: 'Schools on one map.' },
      nav: { about: 'About' },
    };
    const manifest = (fields: Record<string, unknown>): string =>
      JSON.stringify({ ...JSON.parse(cleanManifest), ...fields });
    expect(scanManifest(cleanManifest, 'm.webmanifest', copyTree)).toEqual([]);
    expect(
      scanManifest(
        manifest({ shortcuts: [{ name: 'About', url: '/#about' }] }),
        'm.webmanifest',
        copyTree,
      ),
    ).toEqual([]);
    const messages = (json: string): string[] =>
      scanManifest(json, 'm.webmanifest', copyTree).map((finding) => finding.message);
    expect(messages(manifest({ description: 'Schools on a map.' }))).toEqual([
      'description "Schools on a map." is not copy.manifest.description "Schools on one map."',
    ]);
    expect(messages(manifest({ short_name: 'Snow' }))).toEqual([
      'short_name "Snow" is not copy.manifest.shortName "Snowlight"',
    ]);
    expect(messages(manifest({ shortcuts: [{ name: 'Season Stats' }] }))).toEqual([
      'shortcuts[0].name "Season Stats" is not a string in copy.ts',
      'Title Case "Stats" in shortcuts[0].name: "Season Stats"',
    ]);
    expect(messages('{')).toEqual([expect.stringMatching(/^not valid JSON/u)]);
  });

  it('reports a placeholder that names no string in copy.ts', async () => {
    const findings = await scanIndexHtml(
      '<title>%copy.nope%</title><meta name="description" content="%copy.meta%">',
      { meta: { description: 'Schools on one map.' } },
      'index.html',
    );
    expect(findings.map((finding) => finding.message)).toEqual([
      '%copy.nope% in text is not a string in copy.ts',
      '%copy.meta% in content="…" on <meta> is not a string in copy.ts',
    ]);
  }, 30_000);

  it('holds pages served as they are to the house style, and the built site when asked', async () => {
    const root = project({
      'src/copy.ts': cleanCopy,
      'dist/index.html': '<title>Snowlight beta</title><p>Closed!</p>',
      'dist/manifest.webmanifest': JSON.stringify({ name: 'Snowlight', description: 'Sorry' }),
      'public/404.html': '<title>Snowlight</title><p>This page may have moved</p>',
    });
    const served = 'public/404.html banned phrase "may" in text: "This page may have moved"';
    expect(
      (await lintProject({ root })).findings.map(({ file, message }) => `${file} ${message}`),
    ).toEqual([served]);
    const { findings } = await lintProject({ root, dist: 'dist' });
    expect(findings.map(({ file, message }) => `${file} ${message}`)).toEqual([
      'dist/index.html banned phrase "beta" in text: "Snowlight beta"',
      'dist/index.html exclamation mark in text: "Closed!"',
      'dist/manifest.webmanifest description "Sorry" is not copy.manifest.description "Schools on one map."',
      'dist/manifest.webmanifest banned phrase "sorry" in description: "Sorry"',
      served,
    ]);
  }, 30_000);

  it('passes this project', async () => {
    const { findings, scanned } = await lintProject({ root: WEB_ROOT });
    expect(findings).toEqual([]);
    // copy.ts's strings, and the chance section's fixed words (src/copy-chance.ts).
    expect(scanned.strings).toBe(strings.length + copyLeaves(chanceCopy).length);
    expect(scanned.svelte).toBeGreaterThan(0);
    // The whole site read as one program: about 37 s of one core with the chance section (50 s
    // before its short lists were made distinct pair by pair), and longer on a busy machine.
  }, 120_000);
});

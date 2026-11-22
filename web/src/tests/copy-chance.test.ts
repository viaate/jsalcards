// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { bannedIn, measure } from '../app/tests/plain-reading';
import { chanceCopy, chanceFormat } from '../copy-chance';
import type { OutlookInput, ReasonInput, StepClass } from '../copy-chance';
import { howCopy } from '../copy-how';

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../scripts/check-copy.mjs',
);
const { problems } = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string, file?: string) => string[];
};

const { plain } = chanceFormat;
const { headline, row, build } = plain;
/** Each form filled with each of three names (WHY-PLAIN 5). */
const NAMES = ['Danbury', 'Tahoe-Truckee', 'Creekside Charter'] as const;
const CLASSES: readonly StepClass[] = ['warning', 'advisory', 'cold'];
const ALERTS = [
  'winter_storm_warning',
  'winter_weather_advisory',
  'ice_storm_warning',
  'blizzard_warning',
  'extreme_cold_warning',
  'lake_snow',
  'tropical',
] as const;
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] as const;
const END = '10 AM';
const NBSP = '\u00a0';

/** Every panel template in every form, joined as the panel shows it. */
function forms(): string[] {
  const out: string[] = [
    chanceCopy.fold,
    chanceCopy.fewRecords,
    ...Object.values(plain.part),
    headline.ice,
    headline.cold,
    ...[true, false].flatMap((up) => [headline.held(up), headline.snow(up)]),
    ...[1, 22, 91].flatMap((n) => [plain.why(n), plain.total(n), plain.totalLabel(n)]),
    ...[0.01, 0.09, 0.5].map((q) => chanceFormat.delayInstead(q)),
  ];
  for (const k of CLASSES) {
    out.push(headline.moreCounty(k), headline.fewerCounty(k), headline.region(k, true));
    out.push(headline.region(k, false));
  }
  for (const a of ALERTS) {
    for (const w of WEEKDAYS) {
      out.push(headline.start(a, w), headline.parts(a, w), row.start(a, w, 45));
    }
    out.push(`${row.start(a, 'Wednesday', 45)} ${row.startMoved(42)}`);
    for (const p of [1, 12, 30, 50, 75, 99]) out.push(headline.alertDays(a, p));
    out.push(
      `${row.ordFrom('districts in its county')} ${row.ordAlert(a)} ${row.ordShare(30, false)}`,
    );
  }
  for (const p of [1, 12, 30, 50, 75, 99]) out.push(headline.calm(p), headline.after(p));
  for (const text of [row.offAll, row.unread, row.limit, row.noPast, row.coldDay, row.blizzard]) {
    out.push(text);
  }
  out.push(row.tropical, row.privateDay, row.wait('Wednesday'));
  for (const d of NAMES) {
    out.push(headline.saidOpen(d), row.saidOpen(d));
    for (const k of CLASSES) {
      out.push(headline.moreOwn(d, k), headline.fewerOwn(d, k));
      const ref = { warning: 1.4, advisory: 4, cold: 0.3 }[k];
      const firsts = [
        [row.placeOwn(d, 0, k)],
        [row.placeOwn(d, 1.8, k)],
        [row.placeOwn(d, 1, k)],
        [row.placeCountyPrivate, row.placeCounty(1, k)],
        [row.placeOwn(d, 11.2, k)],
        [row.placeCountyWhy(d), row.placeCounty(0, k)],
        [row.placeCountyWhy(d), row.placeCounty(11.2, k)],
        [row.placeCountyPrivate, row.placeCounty(1.8, k)],
      ];
      for (const first of firsts) {
        for (const sign of [row.placeMore, row.placeFewer, row.placeSame]) {
          for (const middle of [
            [],
            [row.placeRegion(true, 'also')],
            [row.placeRegion(false, 'but')],
            [row.placeRegion(true, null), row.placeHeld],
          ]) {
            for (const dir of [row.down, row.up]) {
              out.push(
                [...first, row.placeRef(ref), sign, ...middle, dir, row.notHabit(d, k)].join(' '),
              );
            }
          }
        }
      }
      out.push(
        `${row.placeUnknown} ${row.placeRegion(false, null)} ${row.up} ${row.notHabitPrivate(k)}`,
      );
      out.push(`${row.fallbackStart(ALERTS[0], 'Wednesday', d, 57)} ${row.fallbackPlace}`);
    }
    for (const who of ['nearby', 'county', 'state', 'region', 'nation']) {
      for (const school of [false, true]) {
        for (const p of [1, 25, 62, 99]) {
          out.push(
            [
              row.ordFrom(plain.ordinaryWhoOf(who, d, school)),
              row.ordCalm,
              row.ordShare(p, false),
            ].join(' '),
          );
          out.push([row.ordOwn(d), row.ordAfter, row.ordShare(p, true)].join(' '));
        }
      }
    }
    // The forecast rows: each school set, snow amount, what joins it and how it ends.
    for (const set of [[], [row.half(d, 'snow')], [row.half(d, 'snow'), row.mainOnly]]) {
      for (const s of [0, 0.4, 1, 4.7, 12]) {
        const lead = [row.snow(s, END), ...set];
        for (const dir of [row.snowMoves(false), row.snowMoves(true), row.same]) {
          for (const usual of [row.usual(5.62, null), row.usual(0.91, 0.8)]) {
            for (const tail of [
              [],
              [row.high],
              [row.low],
              [row.coldLine(-5), row.lowNoChange(false, true)],
              [row.floorSnow, row.coldLine(-5), row.coldAdds],
              [row.floorSnow, row.iceAdds, row.coldLine(4), row.coldSmall],
              [row.iceAdds],
              [row.iceSmall],
              [row.snowSmall],
              [row.capped],
            ]) {
              out.push([...lead, usual, dir, ...tail].join(' '));
            }
          }
          out.push(
            [
              ...lead,
              row.iceJoined('0.12'),
              row.usual(5.62, null),
              dir,
              row.coldLine(12),
              row.lowNoChange(true, true),
            ].join(' '),
          );
          out.push(
            [
              ...lead,
              row.iceJoined(null),
              row.usual(5.62, null),
              dir,
              row.lowNoChange(true, false),
            ].join(' '),
          );
        }
        out.push([...lead, headline.snow(true)].join(' '));
      }
      out.push([row.ice('0.12', END), ...set, row.iceAdds].join(' '));
      out.push([row.ice(null, END), ...set, row.iceAdds].join(' '));
      out.push([row.coldLine(12), row.half(d, 'cold'), row.coldRow].join(' '));
      out.push(
        [row.coldLine(-12), row.half(d, 'cold'), row.mainOnly, row.coldRow, row.capped].join(' '),
      );
    }
  }
  return out;
}

/** Whether a sentence can be said of its input (a form the files never give throws). */
function says(said: () => string): boolean {
  try {
    said();
    return true;
  } catch {
    return false;
  }
}

/** Every line a default row can show in plain words (chanceFormat.plain.line), and every outlook
 * help line under one, in every form, on the school's clock and a viewer's in another zone. */
function lineForms(): string[] {
  const out: string[] = [];
  const DAY = '2026-11-24';
  const at = (iso: string): Date => new Date(iso);
  const NOW = at('2026-11-24T04:00:00Z');
  const BUSES = at('2026-11-24T13:00:00Z');
  const record = (closed: number, remote: number, days: number) => ({
    closed,
    remote,
    days,
    inches: 6,
  });
  const inputs: ReasonInput[] = [];
  for (const points of [9, -4, 0]) {
    for (const against of ['storms', 'advisory', 'here', 'none'] as const) {
      for (const [low, high] of [
        [3, 5],
        [0, 0],
        [4.5, 4.5],
        [null, null],
      ] as const) {
        for (const timing of [
          { overnight: true, until: null },
          { overnight: false, until: at('2026-11-24T18:00:00Z') },
          { overnight: false, until: null },
        ]) {
          for (const cited of [null, record(4, 0, 5), record(1, 1, 1), record(0, 0, 3)]) {
            inputs.push({
              kind: 'snow_total',
              points,
              low,
              high,
              against,
              record: cited,
              ...timing,
            });
          }
        }
      }
    }
    for (const r of [record(4, 0, 5), record(5, 5, 5), record(3, 1, 7), record(0, 0, 1)]) {
      inputs.push({ kind: 'record', points, record: r });
    }
    for (const status of ['closed', 'delayed', 'remote', 'earlyDismissal'] as const) {
      for (const names of [
        null,
        ['Danbury'],
        ['Danbury', 'Tahoe-Truckee'],
        ['Danbury', 'Tahoe-Truckee', 'Creekside Charter', 'Danbury'],
      ]) {
        for (const count of [1, 4]) {
          for (const otherwise of [false, true]) {
            inputs.push({ kind: 'neighbors', points, names, count, status, otherwise });
          }
        }
      }
    }
    for (const kind of ['timing', 'snow_hours'] as const) {
      for (const [start, end] of [
        ['2026-11-24T08:00:00Z', '2026-11-24T12:00:00Z'],
        ['2026-11-24T04:30:00Z', '2026-11-24T08:00:00Z'],
        ['2026-11-24T12:00:00Z', '2026-11-24T15:00:00Z'],
        ['2026-11-24T14:00:00Z', '2026-11-24T19:00:00Z'],
        ['2026-11-24T05:00:00Z', '2026-11-24T07:00:00Z'],
      ] as const) {
        for (const buses of [BUSES, null]) {
          inputs.push({ kind, points, start: at(start), end: at(end), buses });
        }
      }
    }
    for (const feelsLike of [-22, -8, 0, 13, null]) {
      for (const when of [BUSES, null])
        inputs.push({ kind: 'wind_chill', points, feelsLike, at: when });
    }
    for (const feelsLike of [-22, 0, 13])
      inputs.push({ kind: 'cold', points, feelsLike, day: DAY });
    for (const stop of [
      '2026-11-24T02:00:00Z',
      '2026-11-23T20:00:00Z',
      '2026-11-24T16:00:00Z',
      '2026-11-24T13:00:00Z',
      '2026-11-24T10:00:00Z',
    ]) {
      inputs.push({ kind: 'snow_stops', points, at: at(stop), buses: BUSES, day: DAY });
    }
    for (const day of [DAY, '2026-11-25', '2026-11-26']) inputs.push({ kind: 'sun', points, day });
    inputs.push({ kind: 'icy_roads', points, inches: 4 });
    for (const inches of [0.1, 0.25, null]) {
      for (const until of [at('2026-11-24T18:00:00Z'), null]) {
        inputs.push({ kind: 'ice', points, inches, until });
      }
    }
    inputs.push({ kind: 'said_open', points });
  }
  // Each again as the chart or the timeline already says its numbers (`said`).
  for (const input of [...inputs]) {
    switch (input.kind) {
      case 'snow_stops':
        inputs.push({ ...input, said: true, busesSaid: true });
        break;
      case 'snow_total':
      case 'neighbors':
      case 'timing':
      case 'wind_chill':
      case 'cold':
        inputs.push({ ...input, said: true });
        break;
      default:
        break;
    }
  }
  const outlook = (over: Partial<OutlookInput>): OutlookInput => ({
    kind: 'outlook',
    points: 6,
    c0: 0,
    heads: 0,
    forecast: null,
    like: { low: 0, high: 0, heads: 0 },
    to: 5,
    share: 62,
    scope: 'state',
    state: 'KS',
    at: at('2026-11-24T03:00:00Z'),
    generatedAt: at('2026-11-24T03:00:00Z'),
    day: DAY,
    record: at('2026-11-24T11:00:00Z'),
    busTime: BUSES,
    ...over,
  });
  const outlooks: OutlookInput[] = [];
  for (const c0 of [0, 1] as const) {
    for (const heads of [0, 1, 2, 5]) {
      for (const forecast of [
        null,
        { kind: 'snow', low: 6, high: 9 },
        { kind: 'snow', low: 0, high: 2 },
        { kind: 'ice', low: 0.1, high: 0.23 },
        { kind: 'feels', low: -22, high: -15 },
        { kind: 'feels', low: -5, high: 3 },
        { kind: 'feels', low: 4, high: 12 },
      ] as const) {
        for (const scope of ['state', 'region', 'nation'] as const) {
          for (const share of [1, 37, 50, 99, 100]) {
            for (const to of [0, 2, 3, 5]) {
              if (to === c0) continue;
              for (const forecastAt of ['2026-11-24T03:00:00Z', '2026-11-23T20:00:00Z']) {
                outlooks.push(
                  outlook({ c0, heads, forecast, scope, share, to, at: at(forecastAt) }),
                );
              }
            }
          }
        }
      }
    }
  }
  const helps: OutlookInput[] = [];
  for (const generatedAt of [
    '2026-11-23T15:00:00Z',
    '2026-11-23T17:00:00Z',
    '2026-11-23T21:00:00Z',
    '2026-11-24T00:00:00Z',
    '2026-11-24T03:00:00Z',
    '2026-11-24T06:30:00Z',
    '2026-11-24T09:00:00Z',
  ]) {
    for (const c0 of [0, 1] as const) {
      for (const heads of [0, 6, 1, 2, 3, 5]) {
        for (const [low, high] of [
          [0, 13],
          [0, 0],
          [1, 5],
          [2, 3],
          [6, 8],
          [6, 7],
          [9, 12],
          [10, 11],
        ] as const) {
          helps.push(outlook({ c0, like: { low, high, heads }, generatedAt: at(generatedAt) }));
        }
      }
    }
  }
  for (const zones of [
    { school: 'America/Chicago', viewer: 'America/Chicago' },
    { school: 'America/Chicago', viewer: 'America/New_York' },
  ]) {
    for (const d of NAMES) {
      for (const input of [...inputs, ...outlooks]) {
        // Only the forms today's sentence says: plain.line says every one of them.
        if (says(() => chanceFormat.reason(input, d, NOW, zones))) {
          out.push(plain.line(input, d, NOW, zones));
        }
      }
    }
    for (const input of helps) {
      if (says(() => chanceFormat.outlookHelp(input, zones))) {
        out.push(plain.outlookHelp(input, zones));
      }
    }
  }
  return out;
}

/** The copy rules' problems, a name read as "the district". */
function rules(text: string): string[] {
  let plainText = text;
  for (const name of NAMES) plainText = plainText.replaceAll(name, 'the district');
  // A state's name, as the outlook's line gives it, is a name too.
  plainText = plainText.replaceAll('Kansas', 'its state');
  return problems(plainText.replace(/^the district/, 'The district'), 'src/copy-chance.ts');
}

/** The days the habit box's ending names: today, or a weekday. */
const DAYS = [null, ...WEEKDAYS] as const;

/** Every sentence the build-up shows (WHY-V2, COPY-RULES 1 to 5), in every form. */
function buildForms(): string[] {
  const out: string[] = [
    build.saidOpenLine,
    build.recordNone,
    build.recordCannot,
    build.recordUnseen,
    build.heldLine(true),
    build.heldLine(false),
  ];
  for (const k of CLASSES) {
    out.push(build.startLine(k));
    for (const place of [true, false]) {
      for (const snow of ['usual', 'plain', null] as const) {
        for (const joined of ['ice', 'cold', 'both', null] as const) {
          const said = build.still(k, place, snow, joined);
          if (said !== null) out.push(said, `${said} ${row.wait('Monday')}`);
        }
      }
    }
    const ref = { warning: 1.4, advisory: 4, cold: 0.3 }[k];
    for (const f of [0, 0.4, 0.7, 1, 1.8, 2, 2.6, 4, 5.7, 11.2, 30]) {
      out.push(build.placeCount(f, ref));
      for (const more of [row.placeMore, row.placeFewer]) {
        out.push(`${build.placeCount(f, ref)} ${more}`);
        out.push(`${row.placeCountyPrivate} ${build.placeCount(f, ref)} ${more}`);
        out.push(`${row.placeCountyWhy(NAMES[0])} ${build.placeCount(f, ref)} ${more}`);
      }
    }
  }
  for (const [s, u] of [
    [14.3, 5.62],
    [6.1, 3.24],
    [2.4, 1.4],
    [1.5, 1.4],
    [2.5, 0.04],
    [1, 2.4],
    [3.1, 3.4],
    [1.2, 3.24],
    [0, 1.4],
    [2.4, 1.2],
    [0.6, 1.2],
    [0, 0.04],
    [0.3, 0.04],
    [1.8, 1.82],
    [0, 0.03],
  ] as const) {
    out.push(build.snowGap(s, u));
  }
  for (const n of [1, 3, 4, 5, 6, 13, 40]) {
    out.push(build.recordFew(n));
    for (const k of [0, 1, Math.floor(n / 2), n]) {
      out.push(build.recordLead(k, n));
      out.push(`${build.recordLead(k, n)} ${build.recordFew(n)}`);
      for (const near of [0, 0.4, k - 1.4, k + 1.6, n * 0.9, n]) {
        for (const verdict of ['close', 'hold', null] as const) {
          const gap = build.recordGap(k, n, Math.max(0, near), verdict);
          if (gap !== null) out.push(gap, `${build.recordLead(k, n)} ${gap}`);
        }
      }
      out.push(build.recordLists(k, n));
    }
  }
  for (const day of DAYS) {
    for (const n of [1, 15, 59, 99]) {
      out.push(build.notUsed(day, n), build.notStorm(day, n));
      out.push(build.ownLists(day, n));
    }
  }
  return out;
}

/** Every label the build-up shows: titles, the key and the total, short noun phrases. */
function buildLabels(): string[] {
  const out: string[] = [
    build.total,
    ...build.scale(),
    build.startCalm,
    build.startAfter,
    build.regionTitle,
    build.heldTitle,
    build.coldTitle,
  ];
  for (const a of ALERTS) out.push(build.startTitle(a));
  for (const kind of ['snow_total', 'record', 'neighbors', 'timing', 'snow_hours', 'wind_chill']) {
    out.push(build.lineTitle(kind));
  }
  for (const kind of ['cold', 'snow_stops', 'sun', 'icy_roads', 'ice', 'said_open', 'outlook']) {
    out.push(build.lineTitle(kind));
  }
  for (const k of CLASSES) {
    for (const more of [true, false]) {
      for (const f of [0, 1, 4, 11.2]) out.push(build.placeTitle(k, more, f, 4));
    }
    for (const d of NAMES) out.push(build.recordTitle(d, k));
  }
  for (const d of NAMES) out.push(build.saidOpenTitle(d));
  for (const s of [0, 0.4, 1, 4.7, 14.3]) out.push(build.snowTitle(s, `10${NBSP}AM PT`));
  out.push(build.iceTitle(null, END), build.iceTitle('0.12', END), build.iceTitle('1', END));
  for (const k of CLASSES) out.push(build.placeTitle(k, true, 1.4, 1.4));
  for (const n of [1, 6, 13]) out.push(build.keyClosed(n), build.keyRemote(n), build.keySchool(n));
  return out;
}

describe('the build-up reads at grade 6 (WHY-V2)', () => {
  const sentences = [...new Set(buildForms())];

  it('keeps every sentence at grade 6 or under, 15 words a sentence, no banned word, never "like most"', () => {
    const failing: string[] = [];
    for (const text of sentences) {
      const { grade, longest } = measure(text, NAMES);
      if ((grade !== null && grade > 6) || longest > 15 || bannedIn(text).length > 0) {
        failing.push(`${String(grade)} ${String(longest)} ${bannedIn(text).join(',')} | ${text}`);
      }
      if (/like most|[!—]/u.test(text)) failing.push(`mark | ${text}`);
    }
    expect(failing).toEqual([]);
  });

  it('follows the house style in every sentence and label', () => {
    const failing = [...sentences, ...buildLabels()].flatMap((text) =>
      rules(text).map((problem) => `${problem} | ${text}`),
    );
    expect([...new Set(failing)]).toEqual([]);
  });

  it('keeps every label to 9 words or fewer, with no banned word and no sentence end', () => {
    for (const text of buildLabels()) {
      expect([text, text.split(/\s+/u).length <= 9, /[.!?]$/u.test(text)]).toEqual([
        text,
        true,
        false,
      ]);
      expect([text, bannedIn(text)]).toEqual([text, []]);
    }
  });

  it('says the snow gap by its side and size (COPY-RULES 2)', () => {
    expect(build.snowGap(14.3, 5.62)).toBe('More than twice the 5.6 inches usual here.');
    expect(build.snowGap(6.1, 3.24)).toBe('Almost twice the 3.2 inches usual here.');
    expect(build.snowGap(2.4, 1.4)).toBe('About 1 inch more than usual here.');
    expect(build.snowGap(1.5, 1.4)).toBe('A bit more than the 1.4 inches usual here.');
    expect(build.snowGap(1, 2.4)).toBe('Less than half the 2.4 inches usual here.');
    expect(build.snowGap(1.2, 2.4)).toBe('Half the 2.4 inches usual here.');
    expect(build.snowGap(3.1, 5.62)).toBe('About 3 inches less than usual here.');
    expect(build.snowGap(3.1, 3.4)).toBe('A bit less than the 3.4 inches usual here.');
    // A usual that rounds to 0 is never named or doubled.
    expect(build.snowGap(2.4, 0.04)).toBe('About 2 inches more than usual here.');
    // "Twice" and "half" only when exactly so (S3): floored tenths can land on them.
    expect(build.snowGap(2.4, 1.2)).toBe('Twice the 1.2 inches usual here.');
    expect(build.snowGap(0.6, 1.2)).toBe('Half the 1.2 inches usual here.');
    expect(build.snowGap(2.5, 1.2)).toBe('More than twice the 1.2 inches usual here.');
    expect(build.snowGap(0.5, 1.2)).toBe('Less than half the 1.2 inches usual here.');
    // The words hold for the two amounts as the panel shows them, in tenths (LR-V5): equal as
    // shown is "about the", and twice or half as shown is never "more than" or "less than".
    expect(build.snowGap(1.8, 1.82)).toBe('About the 1.8 inches usual here.');
    expect(build.snowGap(1.8, 1.78)).toBe('About the 1.8 inches usual here.');
    expect(build.snowGap(8.4, 4.19)).toBe('Twice the 4.2 inches usual here.');
    expect(build.snowGap(0.4, 0.82)).toBe('Half the 0.8 inches usual here.');
    expect(build.snowGap(2.41, 1.2)).toBe('Twice the 1.2 inches usual here.');
    expect(build.snowGap(0.59, 1.2)).toBe('Half the 1.2 inches usual here.');
    expect(build.snowGap(8.5, 4.19)).toBe('More than twice the 4.2 inches usual here.');
    expect(build.snowGap(0.3, 0.82)).toBe('Less than half the 0.8 inches usual here.');
    expect(build.snowGap(7.4, 4.19)).toBe('Almost twice the 4.2 inches usual here.');
    expect(build.snowGap(7.3, 4.19)).toBe('About 3 inches more than usual here.');
    expect(build.snowGap(0, 0.03)).toBe('A bit less than usual here.');
    // A usual that rounds to 0 is never named on the less side either.
    expect(build.snowGap(0, 0.04)).toBe('A bit less than usual here.');
    expect(build.snowGap(0.3, 0.04)).toBe('A bit more than usual here.');
    // Never "1 inches".
    expect(build.snowGap(1.2, 1)).toBe('A bit more than the 1 inch usual here.');
    for (const [s0, u0] of [
      [2.4, 1.2],
      [0.6, 1.2],
      [0, 0.04],
      [0.3, 0.04],
      [1.2, 1],
      [3, 1],
      [0.4, 1],
    ] as const) {
      expect(build.snowGap(s0, u0)).not.toMatch(/\b0 inches|\b1 inches/u);
    }
    // Never "1 inches" of ice either (LR-V6).
    expect(row.iceJoined('1')).toBe('The forecast also shows at least 1 inch of ice.');
    expect(row.iceJoined('0.25')).toBe('The forecast also shows at least 0.25 inches of ice.');
    expect(row.ice('1', 'noon')).toBe('The forecast shows at least 1 inch of ice by noon.');
    expect(build.iceTitle('1', 'noon')).toBe('At least 1 inch of ice by noon');
    expect(build.snowTitle(14.3, '10 AM PT')).toBe('About 14.3 inches of snow by 10 AM PT');
    expect(build.snowTitle(0.4, 'noon')).toBe('Under 1 inch of snow by noon');
    expect(build.snowTitle(0, 'noon')).toBe('No snow by noon');
  });

  it('says how often the alerts come, "common" and "rare" only at twice or half (COPY-RULES 2)', () => {
    expect(build.placeTitle('warning', true, 11.2, 1.4)).toBe('Storm warnings are common here');
    expect(build.placeTitle('warning', true, 2, 1.4)).toBe('Storm warnings come more often here');
    expect(build.placeTitle('advisory', false, 2, 4)).toBe('Winter advisories are rare here');
    expect(build.placeTitle('advisory', false, 3, 4)).toBe(
      'Winter advisories come less often here',
    );
    // Numbers that read the same take neither side (S4).
    expect(build.placeTitle('warning', true, 1.42, 1.38)).toBe(
      'How often storm warnings come here',
    );
    expect(build.placeTitle('advisory', false, 4.2, 3.9)).toBe(
      'How often winter advisories come here',
    );
    // Two short sentences, the rule's one reads at grade 8.9; "So each one is less likely"
    // has the banned hedge "likely", so the row keeps its own sentence (row.placeMore).
    expect(build.placeCount(11.2, 1.4)).toBe(
      'About 11 a winter. That is 8 times a typical district.',
    );
    expect(build.placeCount(1.8, 4)).toBe(
      'About 1.8 a winter. That is under half a typical district.',
    );
    expect(build.placeCount(5.7, 4)).toBe('About 6 a winter. It is 4 in a typical district.');
    // "Under half" only under half: exactly half (810 published districts with 0.7 storm
    // warnings against 1.4, 118 with 2 advisories against 4) says "half", and so does a count
    // that reads as half once said (1.96 is "2" of "4").
    expect(build.placeCount(0.7, 1.4)).toBe('About 0.7 a winter. That is half a typical district.');
    expect(build.placeCount(2, 4)).toBe('About 2 a winter. That is half a typical district.');
    expect(build.placeCount(1.96, 4)).toBe('About 2 a winter. That is half a typical district.');
    expect(build.placeCount(0.69, 1.4)).toBe(
      'About 0.7 a winter. That is half a typical district.',
    );
    expect(build.placeCount(0.6, 1.4)).toBe(
      'About 0.6 a winter. That is under half a typical district.',
    );
    expect(build.placeCount(0.75, 1.4)).toBe(
      'About 0.8 a winter. It is 1.4 in a typical district.',
    );
    expect(build.placeCount(0, 1.4)).toBe('Almost none a winter. It is 1.4 in a typical district.');
  });

  it('keeps the rule’s own words for every class where they read at grade 6 or under (COPY-RULES 1, 2)', () => {
    const plurals = {
      warning: 'storm warnings',
      advisory: 'winter advisories',
      cold: 'cold warnings',
    };
    for (const k of CLASSES) {
      const one = plurals[k].replace(/ies$/u, 'y').replace(/s$/u, '');
      for (const [rule, built] of [
        [`Every ${one} day starts here.`, build.startLine(k)],
        [`No change from how often ${plurals[k]} come here.`, build.still(k, true, null)],
      ] as const) {
        const ruleGrade = measure(rule, []).grade ?? 0;
        if (ruleGrade <= 6) expect([k, built]).toEqual([k, rule]);
        else expect([k, rule, (measure(built ?? '', []).grade ?? 0) <= 6]).toEqual([k, rule, true]);
      }
    }
  });

  it('says the quiet line once for every part that did not move the chance (COPY-RULES 1)', () => {
    expect(build.still('advisory', true, null)).toBe(
      'There is no change from how often winter advisories come here.',
    );
    // The rule's own words wherever they read at grade 6 or under (only the advisory's do not).
    expect(build.still('warning', true, null)).toBe(
      'No change from how often storm warnings come here.',
    );
    expect(build.still('cold', true, null)).toBe(
      'No change from how often cold warnings come here.',
    );
    // The ice and cold that joined a folded snow row are named with it.
    expect(build.still('warning', false, 'plain', 'ice')).toBe('No change from the snow or ice.');
    expect(build.still('warning', false, 'usual', 'both')).toBe(
      'No change from the snow, ice or cold. The snow is about usual here.',
    );
    expect(build.still('advisory', true, 'plain', 'cold')).toBe(
      'No change from how often winter advisories come here. No change from the snow or cold.',
    );
    expect(build.still('warning', true, 'usual')).toBe(
      'No change from how often storm warnings come here, or from the snow. The snow is about usual here.',
    );
    expect(build.still('advisory', true, 'plain')).toBe(
      'No change from how often winter advisories come here, or from the snow.',
    );
    expect(build.still('warning', false, 'plain')).toBe('No change from the snow.');
    expect(build.still('cold', false, 'usual')).toBe(
      'No change from the snow, which is about usual.',
    );
    expect(build.still('warning', false, null)).toBeNull();
  });

  it('says the past days box in the words of COPY-RULES 3, the few-days form word for word', () => {
    // "days" kept: the rule's "Only 3 on file." grades 6.6 as a sentence alone (see recordFew).
    expect(build.recordFew(3)).toBe('Only 3 days on file. That is too few to tell a habit.');
    expect(build.recordFew(1)).toBe('Only 1 day on file. That is too few to tell a habit.');
    expect(build.recordNone).toBe('None on file yet.');
    // An own base's box never says "none" (the start row says its own days made the chance).
    expect(build.recordUnseen).not.toMatch(/none|no days|not on file/iu);
  });

  it('gives every kind of row its own title, no two alike in their first three words (S6)', () => {
    const kinds = [
      'snow_total',
      'record',
      'neighbors',
      'timing',
      'snow_hours',
      'wind_chill',
      'cold',
      'snow_stops',
      'sun',
      'icy_roads',
      'ice',
      'said_open',
      'outlook',
    ];
    const start = (text: string): string => text.toLowerCase().split(/\s+/u).slice(0, 3).join(' ');
    for (const k of CLASSES) {
      const titles: [string, string][] = [
        ['total', build.total],
        ['region', build.regionTitle],
        ['held', build.heldTitle],
        ['cold row', build.coldTitle],
        ['said open', build.saidOpenTitle('Kansas City')],
        ['snow row', build.snowTitle(4.7, END)],
        ['under row', build.snowTitle(0.4, END)],
        ['no snow row', build.snowTitle(0, END)],
        ['ice row', build.iceTitle('0.12', END)],
        ['little ice row', build.iceTitle(null, END)],
        ['start calm', build.startCalm],
        ['start after', build.startAfter],
        ...ALERTS.map((a): [string, string] => [`start ${a}`, build.startTitle(a)]),
        ['place common', build.placeTitle(k, true, 11.2, 1.4)],
        ['place more', build.placeTitle(k, true, 2, 1.4)],
        ['place rare', build.placeTitle(k, false, 1, 4)],
        ['place less', build.placeTitle(k, false, 3, 4)],
        ['place even', build.placeTitle(k, true, 1.4, 1.4)],
        ...kinds.map((kind): [string, string] => [`line ${kind}`, build.lineTitle(kind)]),
      ];
      // Each start is one alert's own: only one of them is ever in a panel.
      const seen = new Map<string, string>();
      for (const [kind, title] of titles) {
        const key = start(title);
        const other = seen.get(key);
        const both =
          other !== undefined && !(other.startsWith('start') && kind.startsWith('start'));
        const places = other?.startsWith('place') === true && kind.startsWith('place');
        expect([k, kind, other, key, both && !places]).toEqual([k, kind, other, key, false]);
        seen.set(key, kind);
      }
    }
  });

  it('names the day the chance is for, "today’s" only for today (WHY-V2 V3)', () => {
    expect(build.notUsed(null, 15)).toBe('This does not change today’s 15% yet.');
    expect(build.notUsed('Tuesday', 15)).toBe('This does not change Tuesday’s 15% yet.');
    expect(build.notStorm(null, 4)).toBe('Today’s 4% does not come from storm warning days.');
    expect(build.ownLists('Monday', 30)).toBe(
      'Monday’s 30% starts from its days in our past closing lists.',
    );
  });
});

describe('the plain why reads at grade 6', () => {
  const all = [...new Set([...forms(), ...lineForms()])];

  it('fills thousands of forms', () => {
    expect(all.length).toBeGreaterThan(3000);
  });

  it('keeps every panel string at grade 6 or under, 15 words a sentence, no banned word', () => {
    let highest = -99;
    const failing: string[] = [];
    for (const text of all) {
      const { grade, longest } = measure(text, NAMES);
      if (grade !== null) highest = Math.max(highest, grade);
      if ((grade !== null && grade > 6) || longest > 15 || bannedIn(text).length > 0) {
        failing.push(`${String(grade)} ${String(longest)} ${bannedIn(text).join(',')} | ${text}`);
      }
    }
    expect(failing).toEqual([]);
    expect(highest).toBeLessThanOrEqual(6);
  }, 60_000);

  it('follows the house style in every form', () => {
    const failing = all.flatMap((text) => rules(text).map((problem) => `${problem} | ${text}`));
    expect([...new Set(failing)]).toEqual([]);
  }, 60_000);

  it('says how many days had no school true to the published percent, at the ends too', () => {
    expect(plain.shareStart(1)).toBe('Fewer than 1 in 20');
    expect(plain.shareStart(99)).toBe('More than 19 in 20');
    expect(plain.shareStart(50)).toBe('Half');
    expect(plain.shareStart(62)).toBe('More than 3 in 5');
    expect(row.ordShare(25, true)).toBe('1 in 4 of them had no school.');
  });
});

describe('the page How Snowlight guesses', () => {
  const paragraphs = [
    ...howCopy.blocks,
    ...howCopy.sections.flatMap((section) => section.blocks),
  ].flatMap((block) => ('p' in block ? [block.p] : []));

  it('reads at grade 8 or under a paragraph, 20 words a sentence, in the house style', () => {
    for (const text of paragraphs) {
      const { grade, longest } = measure(text, []);
      expect([text, grade === null || grade <= 8.5, longest <= 20]).toEqual([text, true, true]);
      expect([text, problems(text, 'src/copy-how.ts')]).toEqual([text, []]);
    }
  });

  it('says a habit in the owner’s words and a late start, not a delayed one', () => {
    const page = paragraphs.join(' ');
    expect(page).toContain('tends to close easily');
    expect(page).toContain('It tends to hold out');
    expect(page).not.toMatch(/delayed start|close early/u);
  });

  it('never says "like most" and says what the card shows instead (WHY-V2 V2)', () => {
    // Every string in the How page's copy, not only its paragraphs.
    const all = JSON.stringify(howCopy);
    expect(all).not.toMatch(/like most|about like/iu);
    const page = paragraphs.join(' ');
    expect(page).toContain('a bit fewer or more days with no school');
    expect(page).not.toContain('more days off');
    expect(page).toContain('only for a gap of at least 1 day');
  });

  it('says Missouri’s calendar days as lead ruling LR-2 words them, and never that it shows open days', () => {
    const page = paragraphs.join(' ');
    expect(paragraphs).toContain(
      'For schools in Missouri, the state sends us each school day lost to weather. A school day with an alert that is not on that list counts as open. We count a day when a winter alert was out by 9 at night. A make-up day counts as a day with school. A winter advisory day right after a day off is left out.',
    );
    expect(page).toContain('school at home');
    expect(page).not.toMatch(/shows? (the )?(days|open)|stayed open/u);
    for (const paragraph of paragraphs) {
      for (const sentence of (paragraph.match(/[^.]+\./gu) ?? []).map((x) => x.trim())) {
        const { grade } = measure(sentence, []);
        if (paragraph.includes('Missouri')) {
          expect([sentence, grade === null || grade <= 6]).toEqual([sentence, true]);
        }
      }
    }
  });
});

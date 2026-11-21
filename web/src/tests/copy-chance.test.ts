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
const { headline, habit, row } = plain;
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

/** Every panel template in every form, joined as the panel shows it. */
function forms(): string[] {
  const out: string[] = [
    chanceCopy.fold,
    chanceCopy.fewRecords,
    habit.titlePrivate,
    habit.fallback,
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
    for (const w of WEEKDAYS) out.push(headline.start(a, w), row.start(a, w, 45));
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
    out.push(habit.title(d), headline.saidOpen(d), row.saidOpen(d));
    for (const k of CLASSES) {
      out.push(headline.moreOwn(d, k), headline.fewerOwn(d, k));
      for (const peers of ['districts', 'private schools'] as const) {
        for (const [n, closed, late] of [
          [5, 5, 0],
          [6, 3, 1],
          [12, 0, 4],
        ] as const) {
          for (const verdict of [
            habit.early(k, peers),
            habit.holdOut(k, peers),
            habit.likeMost(peers),
          ]) {
            for (const end of [habit.notUsed, habit.notToday]) {
              for (const [othersClosed, othersOf] of [
                [1027, 1071],
                [0, 40],
                [40, 40],
                [999, 1000],
                [1, 1000],
                [20, 40],
                [13, 40],
              ] as const) {
                out.push(
                  [
                    verdict,
                    habit.seen(n, k),
                    habit.counts(n, closed, late),
                    habit.others(peers, othersClosed, othersOf),
                    end,
                  ].join(' '),
                );
              }
            }
          }
        }
      }
      for (const end of [habit.notUsedFew, habit.notToday]) {
        out.push([habit.unknown, habit.seenNone(k), end].join(' '));
        for (const [n, closed, late] of [
          [1, 1, 0],
          [1, 0, 1],
          [1, 0, 0],
          [3, 2, 0],
          [3, 3, 0],
          [2, 2, 0],
          [2, 0, 2],
          [2, 0, 0],
          [4, 2, 1],
        ] as const) {
          out.push(
            [
              habit.unknown,
              habit.seen(n, k),
              habit.counts(n, closed, late),
              habit.tooFew,
              end,
            ].join(' '),
          );
        }
      }
      out.push([habit.seen(3, k), habit.counts(3, 2, 0), habit.ownAlert].join(' '));
      out.push([habit.seenNone(k), habit.ownAlert].join(' '));
      out.push(`${habit.cannot} ${habit.ownAlertAlone(d)}`, `${habit.cannot} ${habit.notToday}`);
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
        for (const dir of [row.less, row.more, row.same]) {
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

/** Every complete-record box (records-mo, lead ruling LR-4): its five sentences at most. */
function fullForms(): string[] {
  const out: string[] = [];
  const shares = [0, 0.004, 0.2, 0.37, 0.433, 0.5, 0.553, 0.71, 0.9, 0.97, 0.995, 1];
  for (const k of CLASSES) {
    for (const [n, none] of [
      [1, 1],
      [1, 0],
      [2, 2],
      [3, 2],
      [6, 6],
      [11, 8],
      [13, 7],
      [17, 0],
    ] as const) {
      for (const verdict of [
        habit.earlyFull,
        habit.holdOutFull,
        habit.likeMost('districts'),
        habit.unknown,
      ]) {
        for (const p of shares) {
          const unknown = verdict === habit.unknown;
          for (const end of [
            unknown ? [habit.tooFew, habit.notUsedFew] : [habit.notUsedFull],
            [habit.notToday],
            [habit.ownAlertFull],
          ]) {
            const near = unknown ? [] : [habit.near(p)];
            out.push(
              [verdict, habit.checked(n, k), habit.noSchool(n, none), ...near, ...end].join(' '),
            );
          }
        }
      }
    }
  }
  return out;
}

describe('a complete record box reads at grade 6, the whole and each sentence alone', () => {
  const boxes = [...new Set(fullForms())];

  it('keeps the whole box and every sentence alone at grade 6, 15 words, five sentences', () => {
    const failing: string[] = [];
    for (const text of boxes) {
      const sentences = (text.match(/[^.]+\./gu) ?? []).map((x) => x.trim());
      if (sentences.length > 5) failing.push(`over 5 | ${text}`);
      for (const part of [text, ...sentences]) {
        const { grade, longest } = measure(part, NAMES);
        if ((grade !== null && grade > 6) || longest > 15 || bannedIn(part).length > 0) {
          failing.push(`${String(grade)} ${String(longest)} | ${part}`);
        }
        if (/[!\u2014]/u.test(part)) failing.push(`mark | ${part}`);
      }
    }
    expect([...new Set(failing)]).toEqual([]);
  }, 60_000);

  it('follows the house style in every box', () => {
    const failing = boxes.flatMap((text) => rules(text).map((problem) => `${problem} | ${text}`));
    expect([...new Set(failing)]).toEqual([]);
  }, 60_000);
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

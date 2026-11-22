/**
 * The why in plain words (WHY-PLAIN, WHY-V2 Direction A, the build-up), for middle schoolers
 * and parents: under the chance one plain reason (the published part that moved it most); then
 * "Why 22%": the start and one row for each part that moved the chance, each with its amount and
 * a bar on one 0 to 100 scale, "All together" once, one quiet line for every part that did not
 * move it, and the district's past days of the kind, what is different first
 * (ui/ChanceSection.svelte). It never changes a chance: every number is a field of the
 * predictions file's why or of the standing file it names (data/standing.ts). Where the standing
 * file is missing or does not match, the rows come from the predictions file alone (the
 * fallback); where neither adds up to the chance, null, and the panel shows no why.
 */

import { chanceFormat } from '../copy-chance';
import type { StepClass, Zones } from '../copy-chance';
import type { ForecastDetail, ReasonDetail } from '../data/forecast-detail';
import type { LocalDate, StandingFile } from '../types/generated';

const plain = chanceFormat.plain;
const { headline, row, build } = plain;

/** One part a joined row adds: its words and its amount. */
export interface PartView {
  readonly label: string;
  readonly number: string;
}

/**
 * One step of the build-up: its amount as said ("45%" for the start, "+12", "−8") and as a
 * number, its title, its plain line (today's sentence for a line row) and, for a joined row, its
 * parts.
 */
export interface WhyRowView {
  readonly key: string;
  readonly number: string;
  readonly points: number;
  readonly title: string;
  readonly text: string;
  /** The one fold, "See each part": each part, then the row's total. Null: no fold. */
  readonly parts: readonly PartView[] | null;
  /** What an outlook line counted, under it, quieter. */
  readonly help?: string;
  /** A 0 row whose published parts are not 0 (they met the bound): it keeps its place. */
  readonly holds?: true;
}

/** A past day of the kind as its mark: closed, remote (school at home) or school. */
export type DayMark = 'closed' | 'remote' | 'school';

/** The district's past days of the kind (the habit box), what is different first. */
export interface HabitView {
  /** "Kansas City’s past storm warning days". */
  readonly title: string;
  /** A complete record's days as marks (closed, then remote, then school), or null. */
  readonly days: readonly DayMark[] | null;
  /** The marks' key, each with its count, only the kinds it has. */
  readonly key: readonly { readonly mark: DayMark; readonly label: string }[];
  /** "No school on all 6.", in strong type, or null. */
  readonly lead: string | null;
  /** The gap, the few days or the lists, or null. */
  readonly text: string | null;
  /** Whether the record changes the chance, on the day it is for, or null. */
  readonly end: string | null;
}

export interface PlainWhyView {
  /** "Why 22%". */
  readonly title: string;
  /** The one plain reason under the chance, or null where none is true to say. */
  readonly headline: string | null;
  /** The start, then each part that moved the chance; they add up to it. */
  readonly rows: readonly WhyRowView[];
  /** The one quiet line for the parts that did not move it, or null. */
  readonly still: string | null;
  /** "All together" and the chance, said once. */
  readonly total: { readonly label: string; readonly number: string };
  readonly habit: HabitView;
}

/** Whose standing: a district by its directory position, or a private school by its place in
 * predictions/latest.json's `schools`. */
export type StepsUnit =
  | { readonly kind: 'district'; readonly index: number }
  | { readonly kind: 'school'; readonly index: number };

export interface StepsSource {
  readonly file: StandingFile;
  readonly unit: StepsUnit;
  /** The file's clauses the forecast broke (its `forecast_check`). */
  readonly forecastCheck: readonly string[];
}

const CLASSES = ['advisory', 'warning', 'cold'] as const;
const CLASS_OF: Readonly<Record<string, StepClass>> = {
  winter_storm_warning: 'warning',
  winter_weather_advisory: 'advisory',
  ice_storm_warning: 'warning',
  blizzard_warning: 'warning',
  extreme_cold_warning: 'cold',
  advisory: 'advisory',
  cold: 'cold',
  lake_snow: 'warning',
  tropical: 'warning',
};

const BORROWED = 1;
const MIXED = 2;
const ONE = 4;

/** The fewest days of one kind a habit is judged on, and how unlikely by luck its gap must be. */
export const HABIT_DAYS = 5;
export const HABIT_LUCK = 0.05;
/**
 * The fewest days with school a "holds out" verdict rests on (records-mo; `habit_record.py`
 * `HABIT_MIN_SCHOOL`): on storm warning days nearly every district near it has no school, so one
 * day read as school held would give the verdict alone. With fewer there is no verdict, never
 * "about like most": the test said it is not.
 */
export const HABIT_MIN_SCHOOL = 2;

type Row4 = readonly [number, number, number, number];
type Row5 = readonly [number, number, number, number, number];
type Row3 = readonly [number, number, number];
type Row7 = readonly [number, number, number, number, number, number, number];

function rowFor<T extends readonly number[]>(
  rows: readonly T[] | undefined,
  index: number,
): T | null {
  return rows?.find((found) => found[0] === index) ?? null;
}

/** The forecast window's end on the day: 18:00 UTC (as chance.ts says the lines' "by 1 PM"). */
function windowEnd(day: LocalDate): Date {
  return new Date(`${day}T18:00:00Z`);
}

/** The weekday of the evening before the day on the school's clock (the 9 PM forecast's). */
function eveningBefore(day: LocalDate, zone: string): string {
  const noon = new Date(`${day}T12:00:00Z`);
  const before = new Date(noon.getTime() - 86_400_000);
  const local = new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(before);
  return chanceFormat.weekday(local);
}

interface Unit {
  readonly name: string;
  readonly school: boolean;
  readonly mixed: boolean;
  readonly one: boolean;
  readonly winter: readonly [number, number, number] | null;
  readonly borrowed: boolean;
  readonly region: number;
  /** The limits' points: the district's, the nation's and rounding's, together. */
  readonly held: number;
  readonly record: { closed: number; late: number; of: number } | null;
  readonly sum: { closed: number; of: number };
  /** Its complete record of the class (a state's calendar file, records-mo), or null: its
   * no-school days, how many of those were school at home, its days, and the districts near it
   * (`same100`, their shares with no school on its days, summed, in hundredths). */
  readonly full: { noSchool: number; home: number; of: number; same100: number } | null;
}

/** A complete record's row as the habit box reads it, or null where it does not add up. */
function fullOf(found: Row7 | null): Unit['full'] {
  if (found === null) return null;
  const [, noSchool, home, , of, same100] = found;
  const whole = [noSchool, home, of, same100].every((n) => Number.isInteger(n) && n >= 0);
  if (!whole || of < 1 || noSchool > of || home > noSchool || same100 > 100 * of) return null;
  return { noSchool, home, of, same100 };
}

/** What the standing file says of one unit and class, or null where it says it wrong. */
function unitOf(source: StepsSource, klass: StepClass, name: string): Unit | null {
  const { file, unit } = source;
  if (unit.kind === 'district') {
    const i = unit.index;
    const flags = file.flags[i];
    if (flags === undefined || i < 0 || i >= file.winter.length) return null;
    const region = rowFor(file.region[klass] as readonly Row3[], i);
    const held = rowFor(file.held[klass] as readonly Row5[], i);
    const record = rowFor(file.record[klass] as readonly Row4[], i);
    const sum = file.record_sum[klass];
    const full = rowFor(file.record_full?.[klass] as readonly Row7[] | undefined, i);
    return {
      name,
      school: false,
      mixed: (flags & MIXED) !== 0,
      one: (flags & ONE) !== 0,
      winter: file.winter[i] ?? null,
      borrowed: (flags & BORROWED) !== 0,
      region: region?.[1] ?? 0,
      held: held === null ? 0 : held[1] + held[2] + held[3],
      record: record === null ? null : { closed: record[1], late: record[2], of: record[3] },
      sum: { closed: sum[0], of: sum[2] },
      full: fullOf(full),
    };
  }
  const privateFile = file.private;
  const at = privateFile.of[unit.index];
  if (at === undefined || at < 0) return null;
  const found = privateFile.rows[at];
  if (found === undefined) return null;
  const [winter, advisoryRegion] = found as unknown as readonly [
    readonly [number, number, number] | null,
    number,
    number,
  ];
  const held = rowFor(privateFile.held[klass] as readonly Row5[], at);
  const record = rowFor(privateFile.record[klass] as readonly Row4[], unit.index);
  const sum = privateFile.record_sum[klass];
  return {
    name,
    school: true,
    mixed: false,
    one: true,
    winter,
    borrowed: true,
    region: klass === 'advisory' ? advisoryRegion : 0,
    held: held === null ? 0 : held[1] + held[2] + held[3],
    record: record === null ? null : { closed: record[1], late: record[2], of: record[3] },
    sum: { closed: sum[0], of: sum[2] },
    full: null,
  };
}

/** P(X <= k) and P(X >= k) for X binomial with n tries and chance p. */
export function tails(n: number, k: number, p: number): { low: number; high: number } {
  let low = 0;
  let high = 0;
  let choose = 1;
  for (let x = 0; x <= n; x += 1) {
    if (x > 0) choose = (choose * (n - x + 1)) / x;
    const mass = choose * p ** x * (1 - p) ** (n - x);
    if (x <= k) low += mass;
    if (x >= k) high += mass;
  }
  return { low, high };
}

/**
 * The habit's verdict (WHY-PLAIN 3c, records-mo): a complete record's no-school days against
 * `p`, the share of the districts near it that had no school on its same days, one-sided exact
 * binomial; null under 5 days or with no share, and null for a "holds out" on fewer than
 * `HABIT_MIN_SCHOOL` days with school. A closings-only record (the lists) never gets one: its open days are mostly
 * unseen, so it is never judged (`habitView`).
 */
export function verdictOf(
  record: { readonly closed: number; readonly of: number },
  p: number,
): 'hold' | 'close' | 'like' | null {
  const { closed: k, of: n } = record;
  if (n < HABIT_DAYS || !(p >= 0 && p <= 1) || k < 0 || k > n) return null;
  const { low, high } = tails(n, k, p);
  if (low < HABIT_LUCK) return n - k >= HABIT_MIN_SCHOOL ? 'hold' : null;
  if (high < HABIT_LUCK) return 'close';
  return 'like';
}

/** What the habit box ends on, and the day and chance it names (WHY-V2 V3). */
interface Ending {
  /** `storm`, a chance counted over days of the kind its record shows, which the habit did not
   * change; `ordinary`, a chance counted over other days than storm warning days (the record
   * shown); `alert`, a chance counted over the district's own past days of the kind. */
  readonly kind: 'storm' | 'ordinary' | 'alert';
  /** The weekday the chance is for, or null when it is for today. */
  readonly day: string | null;
  readonly percent: number;
}

/**
 * The habit box (WHY-V2 3): the title names the district and the kind of day; a complete record
 * shows its days as marks with a key, then the lead, the gap to the districts near it only where
 * the test or a gap of a day says one, and the ending; a closings-only record says what the
 * lists show and is never judged; with none, only that.
 */
function habitView(unit: Unit | null, klass: StepClass, ending: Ending, name: string): HabitView {
  const { day, percent } = ending;
  const title = build.recordTitle(name, klass);
  const empty = { title, days: null, key: [], lead: null };
  if (unit === null) {
    // No standing file to read: only what is true without it. An own base's start row says
    // already that its own past days made the chance, so the box does not say it again.
    const end =
      ending.kind === 'alert'
        ? null
        : ending.kind === 'ordinary'
          ? build.notStorm(day, percent)
          : build.notUsed(day, percent);
    return { ...empty, text: build.recordCannot, end };
  }
  const full = unit.full;
  if (full !== null) {
    const { noSchool, home, of } = full;
    const closed = noSchool - home;
    const school = of - noSchool;
    const days: DayMark[] = [
      ...Array.from({ length: closed }, () => 'closed' as const),
      ...Array.from({ length: home }, () => 'remote' as const),
      ...Array.from({ length: school }, () => 'school' as const),
    ];
    const key = [
      ...(closed > 0 ? [{ mark: 'closed' as const, label: build.keyClosed(closed) }] : []),
      ...(home > 0 ? [{ mark: 'remote' as const, label: build.keyRemote(home) }] : []),
      ...(school > 0 ? [{ mark: 'school' as const, label: build.keySchool(school) }] : []),
    ];
    const p = full.same100 / (100 * of);
    const verdict = verdictOf({ closed: noSchool, of }, p);
    const text =
      of < HABIT_DAYS
        ? build.recordFew(of)
        : build.recordGap(
            noSchool,
            of,
            full.same100 / 100,
            verdict === 'hold' || verdict === 'close' ? verdict : null,
          );
    const end =
      ending.kind === 'alert'
        ? build.ownLists(day, percent)
        : ending.kind === 'ordinary'
          ? build.notStorm(day, percent)
          : build.notUsed(day, percent);
    return { title, days, key, lead: build.recordLead(noSchool, of), text, end };
  }
  // A closings-only record (the lists) is never judged: its open days are mostly unseen.
  const record = unit.record;
  const listed = record !== null && record.of > 0;
  // An own base's start row says already that these days made the chance: no ending again.
  const end =
    ending.kind === 'alert'
      ? null
      : !listed
        ? null
        : ending.kind === 'ordinary'
          ? build.notStorm(day, percent)
          : build.notUsed(day, percent);
  // With no record of the kind, "none on file" only where the chance does not come from its own
  // past days: beside an own base's start row ("This chance comes from {d}'s own past days"),
  // only that the box cannot show them, never "none" (WHY-V2 truth rule).
  const text = listed
    ? build.recordLists(record.closed, record.of)
    : ending.kind === 'alert'
      ? build.recordUnseen
      : build.recordNone;
  return { ...empty, text, end };
}

export interface StepsInput {
  readonly detail: ForecastDetail;
  readonly chance: number;
  readonly day: LocalDate;
  /** The district's short name, or the private school's own. */
  readonly district: string;
  readonly zones: Zones;
  /** The standing file and whose it is; null where it is not read or does not match. */
  readonly source: StepsSource | null;
  /** Each of the why's lines in plain words (chanceFormat.plain.line), in its order (null: one
   * it cannot say). */
  readonly lines: readonly (string | null)[];
  /** What each outlook line counted, by its place in the lines. */
  readonly helps?: readonly (string | undefined)[];
  /** Whether `day` is today on the school's clock: the habit box says "today’s" only then. */
  readonly today?: boolean;
}

/** The why in plain words, or null where neither the full rows nor the fallback add up. */
export function stepsView(input: StepsInput): PlainWhyView | null {
  const percent = Math.round(input.chance * 100);
  const why = input.detail.why;
  if (why === null || percent < 1 || percent > 99) return null;
  const total = why.base.points + why.reasons.reduce((sum, reason) => sum + reason.points, 0);
  if (total !== percent) return null;
  const attempts = [
    () => (why.base.kind === 'class' ? classView(input) : ordinaryView(input)),
    () => (why.base.kind === 'class' ? fallbackView(input) : null),
  ];
  for (const attempt of attempts) {
    try {
      const view = attempt();
      if (view !== null && adds(view, percent)) return view;
    } catch {
      // A number the words refuse: the next way, or no why rather than a wrong one.
    }
  }
  return null;
}

/** The rows' amounts add to the chance, each row's number says its points, and the total says
 * the chance once. */
function adds(view: PlainWhyView, percent: number): boolean {
  const sum = view.rows.reduce((acc, one) => acc + amountOf(one.number), 0);
  if (sum !== percent) return false;
  if (!view.rows.every((one) => amountOf(one.number) === one.points)) return false;
  return view.total.number === `${String(percent)}%` && view.rows[0]?.key === 'start';
}

/** A row's amount as a number: "45%" 45, "−8" -8, "0" 0. */
export function amountOf(label: string): number {
  return Number(label.replace('%', '').replace('−', '-').replace('+', ''));
}

/** The day the habit box names: null for today, else the weekday (WHY-V2 V3). */
function dayNamed(input: StepsInput): string | null {
  return input.today === true ? null : chanceFormat.weekday(input.day);
}

/**
 * The view from its rows: every row that moved the chance, or whose parts did, keeps its place;
 * a 0 row's sentence goes to the quiet line, after `still` (the folded place and snow).
 */
/** A row that moved the chance, or whose parts did: it keeps its place on the panel. */
function moves(one: WhyRowView): boolean {
  return (
    one.points !== 0 ||
    one.holds === true ||
    (one.parts ?? []).some((part) => amountOf(part.number) !== 0)
  );
}

function finish(
  percent: number,
  headlineText: string | null,
  habitBox: HabitView,
  rows: readonly WhyRowView[],
  still: string | null,
): PlainWhyView {
  const moved = (one: WhyRowView): boolean => one.key === 'start' || moves(one);
  const quiet = [
    still,
    ...rows.filter((one) => !moved(one) && one.text !== '').map((one) => one.text),
  ].filter((text): text is string => text !== null);
  return {
    title: plain.why(percent),
    headline: headlineText,
    rows: rows.filter(moved),
    still: quiet.length === 0 ? null : quiet.join(' '),
    total: { label: build.total, number: `${String(percent)}%` },
    habit: habitBox,
  };
}

/** A line the plain rows do not word themselves: said open, or today's sentence. */
function lineRow(input: StepsInput, reason: ReasonDetail, k: number, unitName: string): WhyRowView {
  if (reason.kind === 'said_open') {
    return {
      key: 'said-open',
      number: plain.rowPoints(reason.points),
      points: reason.points,
      title: build.saidOpenTitle(unitName),
      text: build.saidOpenLine,
      parts: null,
    };
  }
  const text = input.lines[k] ?? null;
  if (text === null) throw new RangeError('steps: a line the words cannot say');
  const help = input.helps?.[k];
  return {
    key: `line-${String(k)}-${reason.kind}`,
    number: plain.rowPoints(reason.points),
    points: reason.points,
    title: build.lineTitle(reason.kind),
    text,
    parts: null,
    ...(help === undefined ? {} : { help }),
  };
}

// The storm-class day ----------------------------------------------------------------------

interface ClassDay {
  readonly named: string;
  readonly klass: StepClass;
  readonly school: boolean;
  readonly dayWord: string;
  readonly end: string;
}

function classDayOf(input: StepsInput): ClassDay | null {
  const base = input.detail.why?.base;
  if (base?.kind !== 'class') return null;
  const named = base.alert ?? base.weather ?? null;
  if (named === null) return null;
  const klass = CLASS_OF[named];
  if (klass === undefined) return null;
  return {
    named,
    klass,
    school: base.of === 'private_schools',
    dayWord: chanceFormat.weekday(input.day),
    end: plain.clock(windowEnd(input.day), input.zones),
  };
}

/** The usual snow for a district and kind, as the standing file gives it (inches). */
interface Usual {
  readonly u: number;
  readonly b: number | null;
}

function usualOf(file: StandingFile, klass: StepClass, i: number): Usual | null {
  if (klass === 'cold') return null;
  const usual = file.usual[klass][i];
  if (usual === undefined || usual === null) return null;
  const alone = file.alone[klass][i] ?? null;
  return { u: usual / 100, b: alone === null ? null : alone / 100 };
}

/** The forecast's published parts, which the headline may pick. */
interface ForecastParts {
  readonly snow: number;
  readonly ice: number;
  readonly cold: number;
  readonly saidOpen: number;
}

/** The headline's candidates, in the order ties go. */
const PICKS = ['standing', 'region', 'held', 'snow', 'ice', 'cold', 'saidOpen'] as const;
type Pick = (typeof PICKS)[number];

/** The published part that moved the chance most, up or down; null where every one is 0. */
export function pickOf(parts: Readonly<Record<Pick, number>>): Pick | null {
  let pick: Pick | null = null;
  for (const key of PICKS) {
    if (parts[key] !== 0 && (pick === null || Math.abs(parts[key]) > Math.abs(parts[pick]))) {
      pick = key;
    }
  }
  return pick;
}

/** "That sets this chance." only when the start is the whole chance: every row after it is 0,
 * its fold too (LR-V2); else the parts below add up to it. */
function startOrParts(after: readonly WhyRowView[], alert: string, dayWord: string): string {
  return after.some(moves) ? headline.parts(alert, dayWord) : headline.start(alert, dayWord);
}

function classView(input: StepsInput): PlainWhyView | null {
  const day = classDayOf(input);
  const source = input.source;
  const why = input.detail.why;
  if (day === null || source === null || why === null) return null;
  if (day.school !== (source.unit.kind === 'school')) return null;
  const { klass, named } = day;
  const unit = unitOf(source, klass, input.district);
  if (unit === null) return null;
  const file = source.file;
  const level = file.levels[klass];
  const ref = file.ref[klass];
  const standing = why.base.points - level.now - unit.region - unit.held;
  const days = unit.winter === null ? null : (unit.winter[CLASSES.indexOf(klass)] ?? null);
  if (days === null && standing !== 0) return null;
  if (unit.region !== 0 && klass !== 'advisory') return null;
  const percent = Math.round(input.chance * 100);
  const d = unit.name;

  // The forecast and the lines after it.
  const usual = source.unit.kind === 'district' ? usualOf(file, klass, source.unit.index) : null;
  const forecast = forecastRows(input, day, unit, usual);
  if (forecast === null) return null;

  // The place part's side: the district's days against the typical's as said (neither when
  // they read the same), and whether the part's sign agrees with it.
  const placeAgrees =
    days !== null &&
    plain.perWinter(days) !== plain.perWinter(ref) &&
    (days > ref ? standing < 0 : standing > 0);

  // The headline: the biggest published part after the start, up or down.
  const parts = { standing, region: unit.region, held: unit.held, ...forecast.parts };
  const pick = pickOf(parts);
  let reason: string;
  switch (pick) {
    case null:
      // No part pickOf weighs moved it; a line it does not weigh (timing, hours of snow, when the
      // snow ends, sun) still may, and then the start is not the whole chance (LR-V2).
      reason = startOrParts(forecast.rows, named, day.dayWord);
      break;
    case 'standing': {
      // "More than a typical district" follows the district's days against the typical's, as
      // the place row says them, and only where the part's sign agrees with that side.
      const more = days !== null && days > ref;
      reason = !placeAgrees
        ? headline.parts(named, day.dayWord)
        : unit.school || unit.borrowed
          ? more
            ? headline.moreCounty(klass)
            : headline.fewerCounty(klass)
          : more
            ? headline.moreOwn(d, klass)
            : headline.fewerOwn(d, klass);
      break;
    }
    case 'region':
      reason = headline.region(klass, unit.region > 0);
      break;
    case 'held':
      reason = headline.held(unit.held > 0);
      break;
    case 'snow':
      // "More snow than usual" only where the amounts as shown say so (LR-V5).
      reason = forecast.snowSide
        ? headline.snow(parts.snow > 0)
        : headline.parts(named, day.dayWord);
      break;
    case 'ice':
      reason = headline.ice;
      break;
    case 'cold':
      reason = headline.cold;
      break;
    case 'saidOpen':
      reason = headline.saidOpen(d);
      break;
  }

  const rows: WhyRowView[] = [
    {
      key: 'start',
      number: plain.startLabel(level.now),
      points: level.now,
      title: build.startTitle(named),
      text: [
        build.startLine(klass),
        ...(level.prior !== level.now ? [row.startMoved(level.prior)] : []),
      ].join(' '),
      parts: null,
    },
  ];

  // The place (COPY-RULES 1): how often these alerts come, its part of the country and the
  // limits, each its own row only where it moved the chance, so each title agrees with its sign.
  if (standing !== 0 && days !== null) {
    // The title by the district's days against the typical's as said (neither side when they
    // read the same); "So each one is ..." only where the part's sign agrees with that side,
    // and not when the hero says why already.
    const more = days > ref;
    const said: string[] = [];
    if (unit.school) said.push(row.placeCountyPrivate);
    else if (unit.borrowed) said.push(row.placeCountyWhy(d));
    said.push(build.placeCount(days, ref));
    if (pick !== 'standing' && placeAgrees) said.push(more ? row.placeMore : row.placeFewer);
    rows.push({
      key: 'place',
      number: plain.rowPoints(standing),
      points: standing,
      title: build.placeTitle(klass, more, days, ref),
      text: said.join(' '),
      parts: null,
    });
  }
  if (unit.region !== 0) {
    rows.push({
      key: 'region',
      number: plain.rowPoints(unit.region),
      points: unit.region,
      title: build.regionTitle,
      text: row.placeRegion(unit.region < 0, null),
      parts: null,
    });
  }
  if (unit.held !== 0) {
    rows.push({
      key: 'held',
      number: plain.rowPoints(unit.held),
      points: unit.held,
      title: build.heldTitle,
      text: build.heldLine(unit.held > 0),
      parts: null,
    });
  }
  rows.push(...forecast.rows);

  // What did not move it, in one quiet line: how often these alerts come (where it is known),
  // and the snow.
  const placeQuiet = standing === 0 && days !== null;
  const still = [
    quietOf(forecast, klass, placeQuiet),
    ...(standing === 0 && days === null ? [row.placeUnknown] : []),
  ].filter((text): text is string => text !== null);
  return finish(
    percent,
    reason,
    habitView(unit, klass, { kind: 'storm', day: dayNamed(input), percent }, d),
    rows,
    still.length === 0 ? null : still.join(' '),
  );
}

/** The forecast's rows, its parts, and what a folded snow row leaves to the quiet line: the
 * snow's form and the ice or cold that joined it. */
interface ForecastRows {
  readonly rows: WhyRowView[];
  readonly parts: ForecastParts;
  readonly still: 'usual' | 'plain' | null;
  readonly joined: 'ice' | 'cold' | 'both' | null;
  /** The folded snow row carried the cap's sentence, which the quiet line keeps after it. */
  readonly capped?: true;
  /** The snow's words may say more or less than usual: the amounts as shown agree (LR-V5). */
  readonly snowSide: boolean;
}

/** The quiet line's forecast part: what did not move the chance, then the cap where it held. */
function quietOf(forecast: ForecastRows, k: StepClass, place: boolean): string | null {
  const said = build.still(k, place, forecast.still, forecast.joined);
  return forecast.capped === true && said !== null ? `${said} ${row.capped}` : said;
}

/** The forecast's rows (WHY-PLAIN 3d.3 to 3d.7) and its parts, or null to fall back. */
function forecastRows(
  input: StepsInput,
  day: ClassDay,
  unit: Unit | null,
  usual: Usual | null,
): ForecastRows | null {
  const why = input.detail.why;
  if (why === null) return null;
  const reasons = why.reasons;
  const read = why.read ?? null;
  const d = unit?.name ?? input.district;
  const sumOf = (kind: ReasonDetail['kind']): number =>
    reasons.reduce((sum, reason) => sum + (reason.kind === kind ? reason.points : 0), 0);
  const parts: ForecastParts = {
    snow: sumOf('snow_total'),
    ice: sumOf('ice'),
    cold: sumOf('wind_chill'),
    saidOpen: sumOf('said_open'),
  };
  // A forecast that is not in the chance: a 0 row, which the quiet line says (finish).
  const notIn = (text: string): ForecastRows => ({
    rows: [{ key: 'forecast', number: '0', points: 0, title: '', text, parts: null }],
    parts,
    still: null,
    joined: null,
    snowSide: true,
  });
  const lines = (): ForecastRows => ({
    rows: reasons.map((reason, k) => lineRow(input, reason, k, d)),
    parts,
    still: null,
    joined: null,
    snowSide: true,
  });
  if (day.school) return reasons.length === 0 ? notIn(row.privateDay) : lines();
  if (reasons.length === 0) {
    if (day.klass === 'cold') return notIn(row.coldDay);
    if (day.named === 'blizzard_warning') return notIn(row.blizzard);
    if (day.named === 'tropical') return notIn(row.tropical);
  }
  // No forecast fields: the file says nothing of the forecast, so no row claims one.
  if (read === null) return lines();
  if (read.fc !== null) {
    // fc 6, the bus hour timing: today's sentence for each line, in its place.
    if (reasons.length > 0) return lines();
    switch (read.fc) {
      case 0:
        return notIn(row.wait(eveningBefore(input.day, input.zones.school)));
      case 1:
      case 7:
        return notIn(row.offAll);
      case 2:
      case 3:
        return notIn(row.unread);
      case 4:
      case 5:
        return notIn(row.limit);
      case 8:
      case 9:
        return notIn(row.noPast);
      default:
        return null;
    }
  }
  if (read.snow === null) return null;
  const has = (kind: ReasonDetail['kind']): boolean =>
    reasons.some((reason) => reason.kind === kind);
  const snowLine = has('snow_total');
  const iceLine = has('ice');
  const coldLine = has('wind_chill');
  if (iceLine && read.ice === null) return null;
  if (coldLine && read.feels === null) return null;
  const held = read.held;
  const bound = held === 'low' || held === 'floor';
  // Joining (3d.3): at "low" or "floor" the ice and cold always join the snow; otherwise ice
  // joins only when snow, ice and cold are all published, and a part under 1% always joins.
  // A row is named for what moved the chance (LR-V6): when the snow moved nothing, an ice or
  // cold part that did gets its own row, and the snow folds with only the 0 parts that joined it.
  const alone = (part: number): boolean => parts.snow === 0 && part !== 0;
  const iceJoins =
    read.ice !== null && (bound || !iceLine || (snowLine && coldLine)) && !alone(parts.ice);
  const coldJoins = read.feels !== null && (bound || !coldLine) && !alone(parts.cold);
  const s = Math.floor(read.snow * 10 + 1e-9) / 10;
  const ice = read.ice === null || read.ice === 0 ? null : String(Number(read.ice.toFixed(2)));
  const set = (kind: 'ice' | 'cold'): string[] =>
    unit === null || unit.school || unit.one
      ? []
      : unit.mixed
        ? [row.half(d, kind), row.mainOnly]
        : [row.half(d, kind)];

  // The snow row, with what joins it: the gap to the usual first (WHY-V2 2), where its side
  // agrees with the part's sign; else today's usual and its sentence.
  const snowAmount = parts.snow + (iceJoins ? parts.ice : 0) + (coldJoins ? parts.cold : 0);
  // The snow and the usual in tenths as the panel shows them (LR-V5): "more" only where the
  // shown snow is over the shown usual, "less" only where it is under; where they read equal or
  // the other way, the usual's equal form or the part's sign alone, never a comparison.
  const shown = Math.round(s * 10);
  const shownUsual = usual === null ? null : Math.round(usual.u * 10);
  const snowSide =
    shownUsual === null ||
    parts.snow === 0 ||
    (parts.snow > 0 ? shown > shownUsual : shown < shownUsual);
  const about = shownUsual !== null && Math.abs(shown - shownUsual) < 5;
  const snowSaid: string[] = [];
  if (usual !== null) {
    if (parts.snow === 0)
      snowSaid.push(row.usual(usual.u, usual.b), about ? row.same : row.snowSmall);
    else if (snowSide) snowSaid.push(build.snowGap(s, usual.u));
    else {
      if (shown === shownUsual) snowSaid.push(build.snowGap(s, usual.u));
      snowSaid.push(row.snowMoves(parts.snow > 0));
    }
  } else if (parts.snow !== 0) {
    snowSaid.push(headline.snow(parts.snow > 0));
  }
  // The title's "About" says the snow is the middle of its schools' (COPY-RULES 2).
  if (unit !== null && !unit.school && !unit.one && unit.mixed) snowSaid.push(row.mainOnly);
  if (held === 'low') {
    if (iceJoins) snowSaid.push(row.iceJoined(ice));
    if (coldJoins) snowSaid.push(row.coldLine(read.feels));
    snowSaid.push(iceJoins || coldJoins ? row.lowNoChange(iceJoins, coldJoins) : row.low);
  } else {
    // The snow's own sentences first, then the ice and the cold that joined it, each with its
    // own sentence after it.
    if (held === 'floor') snowSaid.push(row.floorSnow);
    if (held === 'high') snowSaid.push(row.high);
    if (iceJoins) snowSaid.push(row.iceJoined(ice), parts.ice === 0 ? row.iceSmall : row.iceAdds);
    if (coldJoins) {
      snowSaid.push(row.coldLine(read.feels), parts.cold === 0 ? row.coldSmall : row.coldAdds);
    }
  }
  // At "low" the row shows only its total: no part is said to add (lead ruling 2).
  const joinedParts: PartView[] = [];
  if (held !== 'low') {
    if (iceJoins && parts.ice !== 0) {
      joinedParts.push({ label: plain.part.ice, number: plain.rowPoints(parts.ice) });
    }
    if (coldJoins && parts.cold !== 0) {
      joinedParts.push({ label: plain.part.cold, number: plain.rowPoints(parts.cold) });
    }
  }
  const rows: WhyRowView[] = [
    {
      key: 'snow',
      number: plain.rowPoints(snowAmount),
      points: snowAmount,
      title: build.snowTitle(s, day.end),
      text: snowSaid.join(' '),
      parts:
        joinedParts.length > 0
          ? [
              { label: plain.part.snow, number: plain.rowPoints(parts.snow) },
              ...joinedParts,
              { label: plain.part.sum, number: plain.rowPoints(snowAmount) },
            ]
          : null,
    },
  ];
  if (!iceJoins && iceLine) {
    rows.push({
      key: 'ice',
      number: plain.rowPoints(parts.ice),
      points: parts.ice,
      title: build.iceTitle(ice, day.end),
      text: [...set('ice'), row.iceAdds].join(' '),
      parts: null,
    });
  }
  if (!coldJoins && coldLine && read.feels !== null) {
    rows.push({
      key: 'cold',
      number: plain.rowPoints(parts.cold),
      points: parts.cold,
      title: build.coldTitle,
      text: [row.coldLine(read.feels), ...set('cold'), row.coldRow].join(' '),
      parts: null,
    });
  }
  // The cap's sentence goes on the last amount row; a snow row that carries it and folds leaves
  // it to the quiet line, after what did not move the chance.
  const capsSnow = held === 'cap' && rows.length === 1;
  if (held === 'cap') {
    const last = rows.at(-1);
    if (last !== undefined) {
      rows[rows.length - 1] = { ...last, text: `${last.text} ${row.capped}` };
    }
  }
  // The lines that are not the forecast's amounts, in their order: said open, then the rest.
  reasons.forEach((reason, k) => {
    if (reason.kind === 'snow_total' || reason.kind === 'ice' || reason.kind === 'wind_chill') {
      return;
    }
    rows.push(lineRow(input, reason, k, d));
  });
  // A snow row that moved nothing, with no published part that did, folds into the quiet line,
  // which names the ice and cold that joined it too (COPY-RULES 1: every 0 part checked is
  // named). Published parts that met the bound at 0 keep their row (COPY-RULES 5).
  const snowRow = rows[0];
  const published =
    parts.snow !== 0 || (iceJoins && parts.ice !== 0) || (coldJoins && parts.cold !== 0);
  if (snowRow !== undefined && snowAmount === 0 && published) rows[0] = { ...snowRow, holds: true };
  else if (snowRow !== undefined && snowAmount === 0 && snowRow.parts === null) {
    rows.shift();
    const joined = iceJoins ? (coldJoins ? 'both' : 'ice') : coldJoins ? 'cold' : null;
    return {
      rows,
      parts,
      still: about ? 'usual' : 'plain',
      joined,
      ...(capsSnow ? { capped: true as const } : {}),
      snowSide,
    };
  }
  return { rows, parts, still: null, joined: null, snowSide };
}

/** The storm-class day from the predictions file alone (no standing file, or one that does not
 * match): the start as published, then the forecast's rows. */
function fallbackView(input: StepsInput): PlainWhyView | null {
  const day = classDayOf(input);
  const why = input.detail.why;
  if (day === null || why?.base.kind !== 'class') return null;
  const base = why.base;
  const d = input.district;
  const percent = Math.round(input.chance * 100);
  const standing =
    base.standing === 'more'
      ? day.school
        ? headline.moreCounty(day.klass)
        : headline.moreOwn(d, day.klass)
      : base.standing === 'fewer'
        ? day.school
          ? headline.fewerCounty(day.klass)
          : headline.fewerOwn(d, day.klass)
        : row.fallbackPlace;
  const rows: WhyRowView[] = [
    {
      key: 'start',
      number: plain.startLabel(base.points),
      points: base.points,
      title: build.startTitle(day.named),
      text: `${row.fallbackStart(day.named, day.dayWord, day.school ? 'this school' : d, base.points)} ${standing}`,
      parts: null,
    },
  ];
  const forecast = forecastRows(input, day, null, null);
  if (forecast === null) return null;
  rows.push(...forecast.rows);
  const { snow, ice, cold, saidOpen } = forecast.parts;
  const pick = pickOf({ standing: 0, region: 0, held: 0, snow, ice, cold, saidOpen });
  const reason =
    pick === 'snow'
      ? headline.snow(snow > 0)
      : pick === 'ice'
        ? headline.ice
        : pick === 'cold'
          ? headline.cold
          : pick === 'saidOpen'
            ? headline.saidOpen(d)
            : startOrParts(forecast.rows, day.named, day.dayWord);
  return finish(
    percent,
    reason,
    habitView(null, day.klass, { kind: 'storm', day: dayNamed(input), percent }, d),
    rows,
    quietOf(forecast, day.klass, false),
  );
}

// The ordinary day -------------------------------------------------------------------------

function ordinaryView(input: StepsInput): PlainWhyView | null {
  const why = input.detail.why;
  if (why === null) return null;
  const base = why.base;
  if (base.kind === 'class') return null;
  const percent = Math.round(input.chance * 100);
  const d = input.district;
  const school = base.kind === 'pooled' && base.of === 'private_schools';
  const p = base.points;
  const weather = 'weather' in base ? (base.weather ?? null) : null;
  let text: string;
  let reason: string | null;
  // The habit box shows the record of the kind of day the base counted (storm warning days
  // where it counted none), and says truly whether that record made the chance: a district's
  // own days of an alert or weather did; a pool's did not; any other day's chance does not come
  // from storm warning days.
  const counted = base.kind === 'alert' || base.kind === 'pooled' ? base.alert : null;
  const named = counted ?? weather;
  const klass: StepClass = named === null ? 'warning' : (CLASS_OF[named] ?? 'warning');
  if (named !== null && CLASS_OF[named] === undefined) return null;
  const ending: 'storm' | 'ordinary' | 'alert' =
    named === null ? 'ordinary' : base.kind === 'pooled' ? 'storm' : 'alert';
  // The start's title names the alert or the calm day, so its line does not say it again.
  switch (base.kind) {
    case 'alert':
      text = `${row.ordOwn(d)} ${row.ordShare(p, true)}`;
      // Counted over other days than the day's own: no claim of what is out today.
      reason = base.borrowed ? null : headline.alertDays(base.alert, p);
      break;
    case 'day_after':
      text = `${row.ordOwn(d)} ${row.ordAfter} ${row.ordShare(p, true)}`;
      reason = headline.after(p);
      break;
    case 'similar_days': {
      text = `${row.ordOwn(d)} ${row.ordShare(p, true)}`;
      reason = base.borrowed
        ? null
        : weather === null
          ? headline.calm(p)
          : headline.alertDays(weather, p);
      break;
    }
    case 'pooled': {
      text = `${row.ordFrom(plain.ordinaryWhoOf(base.scope, d, school))} ${row.ordShare(p, false)}`;
      reason = base.borrowed
        ? null
        : named === null
          ? headline.calm(p)
          : headline.alertDays(named, p);
      break;
    }
  }
  const title =
    named !== null
      ? build.startTitle(named)
      : base.kind === 'day_after'
        ? build.startAfter
        : build.startCalm;
  const rows: WhyRowView[] = [
    { key: 'start', number: plain.startLabel(p), points: p, title, text, parts: null },
    ...why.reasons.map((line, k) => lineRow(input, line, k, d)),
  ];
  const source = input.source;
  const unit =
    source !== null && school === (source.unit.kind === 'school') ? unitOf(source, klass, d) : null;
  return finish(
    percent,
    reason,
    habitView(unit, klass, { kind: ending, day: dayNamed(input), percent }, d),
    rows,
    null,
  );
}

/**
 * The why in plain words (WHY-PLAIN), for middle schoolers and parents: under the chance one
 * plain reason (the published part that moved it most); then "Why 22%", the district's habit in
 * a box with the owner's question as its title, at most four short rows that add up to the
 * chance, each with its amount, a total line, and at most one fold that lists the parts of a row
 * that joins more than one (ui/ChanceSection.svelte). It never changes a chance: every number
 * is a field of the predictions file's why or of the standing file it names
 * (data/standing.ts). Where the standing file is missing or does not match, the rows come from
 * the predictions file alone (the fallback); where neither adds up to the chance, null, and the
 * panel shows no why.
 */

import { chanceFormat } from '../copy-chance';
import type { StepClass, Zones } from '../copy-chance';
import type { ForecastDetail, ReasonDetail } from '../data/forecast-detail';
import type { LocalDate, StandingFile } from '../types/generated';

const plain = chanceFormat.plain;
const { headline, habit, row } = plain;

/** One part a joined row adds: its words and its amount. */
export interface PartView {
  readonly label: string;
  readonly number: string;
}

/** One row: its amount, its sentences (one paragraph) and, for a joined row, its parts. */
export interface WhyRowView {
  readonly key: string;
  readonly number: string;
  readonly text: string;
  /** The one fold, "See each part": each part, then the row's total. Null: no fold. */
  readonly parts: readonly PartView[] | null;
  /** What an outlook line counted, under it, quieter. */
  readonly help?: string;
}

export interface PlainWhyView {
  /** "Why 22%". */
  readonly title: string;
  /** The one plain reason under the chance, or null where none is true to say. */
  readonly headline: string | null;
  /** The habit box: the owner's question, then one paragraph. */
  readonly habit: { readonly title: string; readonly text: string };
  readonly rows: readonly WhyRowView[];
  /** "= 22%" and "Add these up and you get 22%.", with 2 or more rows. */
  readonly total: { readonly label: string; readonly text: string } | null;
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

type Row4 = readonly [number, number, number, number];
type Row5 = readonly [number, number, number, number, number];
type Row3 = readonly [number, number, number];

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
 * The habit's verdict (WHY-PLAIN 3c): with 5 or more days of the kind, the unit against the
 * others in the same lists (`record_sum` less its own days), one-sided exact binomial; null
 * under 5 days or where the sums cannot give a share.
 */
export function verdictOf(
  record: { readonly closed: number; readonly of: number },
  sum: { readonly closed: number; readonly of: number },
): 'hold' | 'close' | 'like' | null {
  const { closed: k, of: n } = record;
  if (n < HABIT_DAYS) return null;
  const others = sum.of - n;
  const othersClosed = sum.closed - k;
  if (others <= 0 || othersClosed < 0 || othersClosed > others) return null;
  const { low, high } = tails(n, k, othersClosed / others);
  if (low < HABIT_LUCK) return 'hold';
  if (high < HABIT_LUCK) return 'close';
  return 'like';
}

/**
 * The habit box's paragraph for a unit and kind of day, ending as `ending` says: `storm`, a
 * chance counted over days of the kind its record shows, which the habit did not change;
 * `ordinary`, a chance counted over other days than storm warning days (the record shown);
 * `alert`, a chance counted over the district's own past days of the kind.
 */
function habitText(
  unit: Unit | null,
  klass: StepClass,
  ending: 'storm' | 'ordinary' | 'alert',
  name: string,
): string {
  if (unit === null) {
    // No standing file to read: only what is true without it.
    if (ending === 'alert') return `${habit.cannot} ${habit.ownAlertAlone(name)}`;
    if (ending === 'ordinary') return `${habit.cannot} ${habit.notToday}`;
    return habit.fallback;
  }
  const peers = unit.school ? 'private schools' : 'districts';
  const record = unit.record;
  const n = record?.of ?? 0;
  const said: string[] = [];
  const verdict = record === null ? null : verdictOf(record, unit.sum);
  if (ending === 'alert') {
    // Its own days like today's made the chance (the row below counts them), which can be fewer
    // than the class record shown here: no verdict, the record as the class's days, then that.
    // With no record, only that it is not known, never "no days" beside "comes from".
    if (n === 0) said.push(habit.unknown);
  } else if (verdict === null) {
    said.push(habit.unknown);
  } else {
    said.push(
      verdict === 'hold'
        ? habit.holdOut(klass, peers)
        : verdict === 'close'
          ? habit.early(klass, peers)
          : habit.likeMost(peers),
    );
  }
  if (ending === 'alert' && n === 0) {
    // Said above.
  } else if (record === null || n === 0) {
    said.push(habit.seenNone(klass));
  } else {
    said.push(habit.seen(n, klass), habit.counts(n, record.closed, record.late));
  }
  // With a verdict, what the others did: the share it is tested against.
  if (verdict !== null && record !== null && ending !== 'alert') {
    said.push(habit.others(peers, unit.sum.closed - record.closed, unit.sum.of - n));
  }
  if (ending === 'alert') return [...said, habit.ownAlert].join(' ');
  if (verdict === null && n >= 1) said.push(habit.tooFew);
  said.push(
    ending === 'ordinary' ? habit.notToday : verdict === null ? habit.notUsedFew : habit.notUsed,
  );
  return said.join(' ');
}

function habitTitle(name: string, school: boolean): string {
  return school ? habit.titlePrivate : habit.title(name);
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

/** The rows' amounts add to the chance, and the total line says it. */
function adds(view: PlainWhyView, percent: number): boolean {
  const sum = view.rows.reduce((acc, one) => acc + amountOf(one.number), 0);
  if (sum !== percent) return false;
  if (view.rows.length >= 2) return view.total?.label === plain.totalLabel(percent);
  return view.total === null;
}

/** A row's amount as a number: "45%" 45, "−8" -8, "0" 0. */
export function amountOf(label: string): number {
  return Number(label.replace('%', '').replace('−', '-').replace('+', ''));
}

function finish(
  percent: number,
  headlineText: string | null,
  habitBox: { title: string; text: string },
  rows: WhyRowView[],
): PlainWhyView {
  return {
    title: plain.why(percent),
    headline: headlineText,
    habit: habitBox,
    rows,
    total:
      rows.length >= 2 ? { label: plain.totalLabel(percent), text: plain.total(percent) } : null,
  };
}

/** A line the plain rows do not word themselves: said open, or today's sentence. */
function lineRow(input: StepsInput, reason: ReasonDetail, k: number, unitName: string): WhyRowView {
  if (reason.kind === 'said_open') {
    return {
      key: 'said-open',
      number: plain.rowPoints(reason.points),
      text: row.saidOpen(unitName),
      parts: null,
    };
  }
  const text = input.lines[k] ?? null;
  if (text === null) throw new RangeError('steps: a line the words cannot say');
  const help = input.helps?.[k];
  return {
    key: `line-${String(k)}-${reason.kind}`,
    number: plain.rowPoints(reason.points),
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
  const rows: WhyRowView[] = [];

  // The start.
  rows.push({
    key: 'start',
    number: plain.startLabel(level.now),
    text: [
      row.start(named, day.dayWord, level.now),
      ...(level.prior !== level.now ? [row.startMoved(level.prior)] : []),
    ].join(' '),
    parts: null,
  });

  // The place: how often these alerts come, its part of the country, the limits.
  const place = standing + unit.region + unit.held;
  const said: string[] = [];
  if (days === null) {
    said.push(row.placeUnknown);
  } else {
    if (unit.school) said.push(row.placeCountyPrivate, row.placeCounty(days, klass));
    else if (unit.borrowed) said.push(row.placeCountyWhy(d), row.placeCounty(days, klass));
    else said.push(row.placeOwn(d, days, klass));
    said.push(row.placeRef(ref));
    said.push(standing < 0 ? row.placeMore : standing > 0 ? row.placeFewer : row.placeSame);
  }
  if (unit.region !== 0) {
    const join =
      standing === 0 || days === null ? null : standing < 0 === unit.region < 0 ? 'also' : 'but';
    said.push(row.placeRegion(unit.region < 0, join));
  }
  if (unit.held !== 0) said.push(row.placeHeld);
  if (place < 0) said.push(row.down);
  if (place > 0) said.push(row.up);
  said.push(unit.school ? row.notHabitPrivate(klass) : row.notHabit(d, klass));
  const joined = unit.region !== 0 || unit.held !== 0;
  rows.push({
    key: 'place',
    number: plain.rowPoints(place),
    text: said.join(' '),
    parts: joined
      ? [
          { label: plain.part.standing, number: plain.rowPoints(standing) },
          ...(unit.region !== 0
            ? [{ label: plain.part.region, number: plain.rowPoints(unit.region) }]
            : []),
          ...(unit.held !== 0
            ? [{ label: plain.part.held, number: plain.rowPoints(unit.held) }]
            : []),
          { label: plain.part.sum, number: plain.rowPoints(place) },
        ]
      : null,
  });

  // The forecast and the lines after it.
  const usual = source.unit.kind === 'district' ? usualOf(file, klass, source.unit.index) : null;
  const forecast = forecastRows(input, day, unit, usual);
  if (forecast === null) return null;
  rows.push(...forecast.rows);

  // The headline: the biggest published part after the start, up or down.
  const parts = { standing, region: unit.region, held: unit.held, ...forecast.parts };
  let reason: string;
  switch (pickOf(parts)) {
    case null:
      reason = headline.start(named, day.dayWord);
      break;
    case 'standing': {
      // "More than a typical district" follows the district's days against the typical's.
      const more = days !== null && days !== ref ? days > ref : standing < 0;
      reason =
        unit.school || unit.borrowed
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
      reason = headline.snow(parts.snow > 0);
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
  return finish(
    percent,
    reason,
    { title: habitTitle(d, unit.school), text: habitText(unit, klass, 'storm', d) },
    rows,
  );
}

/** The forecast's rows (WHY-PLAIN 3d.3 to 3d.7) and its parts, or null to fall back. */
function forecastRows(
  input: StepsInput,
  day: ClassDay,
  unit: Unit | null,
  usual: Usual | null,
): { rows: WhyRowView[]; parts: ForecastParts } | null {
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
  const notIn = (text: string): WhyRowView[] => [
    { key: 'forecast', number: '0', text, parts: null },
  ];
  const lines = (): WhyRowView[] => reasons.map((reason, k) => lineRow(input, reason, k, d));
  if (day.school) return { rows: reasons.length === 0 ? notIn(row.privateDay) : lines(), parts };
  if (reasons.length === 0) {
    if (day.klass === 'cold') return { rows: notIn(row.coldDay), parts };
    if (day.named === 'blizzard_warning') return { rows: notIn(row.blizzard), parts };
    if (day.named === 'tropical') return { rows: notIn(row.tropical), parts };
  }
  // No forecast fields: the file says nothing of the forecast, so no row claims one.
  if (read === null) return { rows: lines(), parts };
  if (read.fc !== null) {
    // fc 6, the bus hour timing: today's sentence for each line, in its place.
    if (reasons.length > 0) return { rows: lines(), parts };
    switch (read.fc) {
      case 0:
        return { rows: notIn(row.wait(eveningBefore(input.day, input.zones.school))), parts };
      case 1:
      case 7:
        return { rows: notIn(row.offAll), parts };
      case 2:
      case 3:
        return { rows: notIn(row.unread), parts };
      case 4:
      case 5:
        return { rows: notIn(row.limit), parts };
      case 8:
      case 9:
        return { rows: notIn(row.noPast), parts };
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
  const iceJoins = read.ice !== null && (bound || !iceLine || (snowLine && coldLine));
  const coldJoins = read.feels !== null && (bound || !coldLine);
  const s = Math.floor(read.snow * 10 + 1e-9) / 10;
  const ice = read.ice === null || read.ice === 0 ? null : String(Number(read.ice.toFixed(2)));
  const set = (kind: 'snow' | 'under' | 'ice' | 'cold'): string[] =>
    unit === null || unit.school || unit.one
      ? []
      : unit.mixed
        ? [row.half(d, kind), row.mainOnly]
        : [row.half(d, kind)];

  // The snow row, with what joins it.
  const snowAmount = parts.snow + (iceJoins ? parts.ice : 0) + (coldJoins ? parts.cold : 0);
  const snowSaid: string[] = [row.snow(s, day.end), ...set(s < 1 ? 'under' : 'snow')];
  if (iceJoins) snowSaid.push(row.iceJoined(ice));
  if (usual !== null) {
    snowSaid.push(row.usual(usual.u, usual.b));
    // At 0, "about that much" only where it is: else the snow moved it under 1%.
    snowSaid.push(
      parts.snow < 0
        ? row.less
        : parts.snow > 0
          ? row.more
          : Math.abs(s - usual.u) < 0.5
            ? row.same
            : row.snowSmall,
    );
  } else if (parts.snow !== 0) {
    snowSaid.push(headline.snow(parts.snow > 0));
  }
  if (held === 'low') {
    if (coldJoins) snowSaid.push(row.coldLine(read.feels));
    snowSaid.push(iceJoins || coldJoins ? row.lowNoChange(iceJoins, coldJoins) : row.low);
  } else {
    if (held === 'floor') snowSaid.push(row.floorSnow);
    if (held === 'high') snowSaid.push(row.high);
    if (iceJoins) snowSaid.push(parts.ice === 0 ? row.iceSmall : row.iceAdds);
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
      text: [row.ice(ice, day.end), ...set('ice'), row.iceAdds].join(' '),
      parts: null,
    });
  }
  if (!coldJoins && coldLine && read.feels !== null) {
    rows.push({
      key: 'cold',
      number: plain.rowPoints(parts.cold),
      text: [row.coldLine(read.feels), ...set('cold'), row.coldRow].join(' '),
      parts: null,
    });
  }
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
  return { rows, parts };
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
            : headline.start(day.named, day.dayWord);
  return finish(percent, reason, { title: habitTitle(d, day.school), text: habit.fallback }, rows);
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
  switch (base.kind) {
    case 'alert':
      text = `${row.ordOwn(d)} ${row.ordAlert(base.alert)} ${row.ordShare(p, true)}`;
      // Counted over other days than the day's own: no claim of what is out today.
      reason = base.borrowed ? null : headline.alertDays(base.alert, p);
      break;
    case 'day_after':
      text = `${row.ordOwn(d)} ${row.ordAfter} ${row.ordShare(p, true)}`;
      reason = headline.after(p);
      break;
    case 'similar_days': {
      const tail = weather === null ? row.ordCalm : row.ordAlert(weather);
      text = `${row.ordOwn(d)} ${tail} ${row.ordShare(p, true)}`;
      reason = base.borrowed
        ? null
        : weather === null
          ? headline.calm(p)
          : headline.alertDays(weather, p);
      break;
    }
    case 'pooled': {
      const tail = named === null ? row.ordCalm : row.ordAlert(named);
      text = `${row.ordFrom(plain.ordinaryWhoOf(base.scope, d, school))} ${tail} ${row.ordShare(p, false)}`;
      reason = base.borrowed
        ? null
        : named === null
          ? headline.calm(p)
          : headline.alertDays(named, p);
      break;
    }
  }
  const rows: WhyRowView[] = [
    { key: 'start', number: plain.startLabel(p), text, parts: null },
    ...why.reasons.map((line, k) => lineRow(input, line, k, d)),
  ];
  const source = input.source;
  const unit =
    source !== null && school === (source.unit.kind === 'school') ? unitOf(source, klass, d) : null;
  return finish(
    percent,
    reason,
    {
      title: habitTitle(d, school),
      text: habitText(unit, klass, ending, school ? 'this school' : d),
    },
    rows,
  );
}

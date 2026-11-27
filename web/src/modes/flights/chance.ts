/**
 * What an airport's chances say, block by block, and what a flight's two ends say together
 * (flights spec D6, D13, D21 pattern 1). Pure functions over the live file's rows; nothing here
 * makes a number up: a block with no value stays without one, and a value that is the usual
 * rate is marked as such everywhere it goes.
 */
import type { FlightsAirportLive, FlightsBlockRow, LocalDate } from '../../types/generated';

/** Blocks per day, early first (the files' order). */
export const BLOCK_COUNT = 5;
/** Each block's first local minute: early 5, morning 9, afternoon 12, evening 17, night 21. */
export const BLOCK_STARTS = [300, 540, 720, 1020, 1260] as const;

/**
 * The lines between the levels, in whole percent: the number the traveler sees (LR-F15.1). A day
 * or a flight is high risk of cancel at 15% or more; some risk at 5% cancel or 25% leaving 45+
 * minutes late; low risk below both. The usual cancel share of a US departure is about 1 to 2%,
 * and of a 45+ minute late one about 5 to 9%, so the lines sit well above an ordinary day.
 */
export const CANCEL_HIGH = 15;
export const CANCEL_SOME = 5;
export const LATE_SOME = 25;

export type Level = 'low' | 'delay' | 'cancel';

/**
 * A per mille value (the files' unit) as the whole percent the page shows it (copy-flights.ts
 * percent): every level, color and rank is worked out from this, never from the raw value, so two
 * times that show the same numbers always get the same level and rank (LR-F15.1).
 */
export function wholePercent(perMille: number): number {
  return Math.round(perMille / 10);
}

/** The level of a cancel and a late chance (per mille), from the whole percents shown. */
export function levelOf(cancel: number, late: number): Level {
  const shownCancel = wholePercent(cancel);
  if (shownCancel >= CANCEL_HIGH) return 'cancel';
  if (shownCancel >= CANCEL_SOME || wholePercent(late) >= LATE_SOME) return 'delay';
  return 'low';
}

/** Two independent chances of trouble, at least one: 1 - (1 - a)(1 - b), in tenths of a percent. */
export function either(a: number, b: number): number {
  return Math.round(1000 - ((1000 - a) * (1000 - b)) / 1000);
}

/** The block a local minute of the day falls in, and whether it is the night block of the day before. */
export function blockOfMinute(minute: number): { block: number; dayBefore: boolean } {
  const m = ((minute % 1440) + 1440) % 1440;
  if (m < BLOCK_STARTS[0]) return { block: 4, dayBefore: true };
  let block = 0;
  for (let i = 0; i < BLOCK_COUNT; i += 1) if (m >= (BLOCK_STARTS[i] ?? 0)) block = i;
  return { block, dayBefore: false };
}

/** A local date `days` after `day`. */
export function addDays(day: LocalDate, days: number): LocalDate {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Monday 0 to Sunday 6, as the usual flights' weekday bits count them. */
export function weekdayIndex(day: LocalDate): number {
  return (new Date(`${day}T12:00:00Z`).getUTCDay() + 6) % 7;
}

/** The local date and minute of `at` in `zone`. */
/** One formatter per zone: making one is slow, and the map asks for every airport at once. */
const FORMATS = new Map<string, Intl.DateTimeFormat>();

function formatIn(zone: string): Intl.DateTimeFormat {
  let format = FORMATS.get(zone);
  if (format === undefined) {
    format = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    FORMATS.set(zone, format);
  }
  return format;
}

/**
 * Local parts already worked out, by zone and whole minute: the map's airports share a few
 * zones and ask for the same minute, and each formatting costs as much as the rest of a day's
 * reckoning. Cleared once it grows, so it never holds more than a few thousand.
 */
const PARTS = new Map<string, { day: LocalDate; minute: number }>();
const PARTS_HELD = 4096;

export function localParts(at: Date, zone: string): { day: LocalDate; minute: number } {
  const key = `${zone} ${String(Math.floor(at.getTime() / 60_000))}`;
  const held = PARTS.get(key);
  if (held !== undefined) return held;
  const parts = formatIn(zone).formatToParts(at);
  const get = (type: string): string => parts.find((part) => part.type === type)?.value ?? '00';
  const local = {
    day: `${get('year')}-${get('month')}-${get('day')}`,
    minute: Number(get('hour')) * 60 + Number(get('minute')),
  };
  if (PARTS.size >= PARTS_HELD) PARTS.clear();
  PARTS.set(key, local);
  return local;
}

/** The instant a local date and minute is in `zone`. */
export function instantOf(day: LocalDate, minute: number, zone: string): Date {
  const wall = Date.parse(`${day}T00:00:00Z`) + minute * 60_000;
  // The zone's offset at that wall time, found from a first guess and checked once (DST edges).
  let guess = wall;
  for (let i = 0; i < 2; i += 1) {
    const seen = localParts(new Date(guess), zone);
    const seenWall = Date.parse(`${seen.day}T00:00:00Z`) + seen.minute * 60_000;
    guess += wall - seenWall;
  }
  return new Date(guess);
}

/**
 * Each block's end, in local minutes from the start of its day: early 9, morning 12, afternoon
 * 17, evening 21, and the night at 5 the next morning.
 */
export const BLOCK_ENDS = [540, 720, 1020, 1260, 1740] as const;

/** The local date now in `zone`. */
export function localToday(zone: string, now: number): LocalDate {
  return localParts(new Date(now), zone).day;
}

/**
 * `now` as a wall clock in `zone`, in milliseconds from the epoch as if the zone were UTC: one
 * formatting per zone, so a day's five blocks (and the map's every airport) cost one each.
 */
export function wallNow(zone: string, now: number): number {
  const local = localParts(new Date(now), zone);
  return Date.parse(`${local.day}T00:00:00Z`) + local.minute * 60_000;
}

/** Whether block `block` of local `day` has ended by the wall clock `wall` (wallNow). */
export function blockOverAt(day: LocalDate, block: number, wall: number): boolean {
  return Date.parse(`${day}T00:00:00Z`) + (BLOCK_ENDS[block] ?? 1740) * 60_000 <= wall;
}

/** Whether block `block` of local `day` in `zone` has ended by `now`. */
export function blockOver(day: LocalDate, block: number, zone: string, now: number): boolean {
  return blockOverAt(day, block, wallNow(zone, now));
}

/** One block of one day at one airport. */
export interface BlockValue {
  readonly cancel: number | null;
  readonly late: number | null;
  /** Whether each value is the usual rate, not a forecast. */
  readonly cancelUsual: boolean;
  readonly lateUsual: boolean;
  /** Whether either value is the usual rate. */
  readonly usual: boolean;
  /** Whether the block has ended by now, in the airport's zone: its values are shown as over. */
  readonly over: boolean;
}

/**
 * What a day's answer may say. `level`: a level, from forecast values only. `usual`: the values
 * left are (some of them) the usual rate and no forecast among them shows risk, so no level word
 * is given, only the usual rate as itself. `none`: no value is left for the day.
 */
export type DayAnswer = 'level' | 'usual' | 'none';

/** One day at one airport, as of now. */
export interface DayView {
  readonly index: number;
  readonly day: LocalDate;
  readonly blocks: readonly BlockValue[];
  /** The highest cancel and late chances over the blocks not over yet; null with none. */
  readonly cancel: number | null;
  readonly late: number | null;
  /** The level, from forecast values only; null where the answer is not a level. */
  readonly level: Level | null;
  readonly answer: DayAnswer;
  /** Whether a value left is the usual rate. */
  readonly usual: boolean;
}

function bit(mask: number, i: number): boolean {
  return (mask & (1 << i)) !== 0;
}

/** The level forecast values give, and whether the usual rate stands anywhere among the rest. */
export function answerOf(
  forecastCancel: number | null,
  forecastLate: number | null,
  anyUsual: boolean,
): { level: Level | null; answer: DayAnswer } {
  const forecast =
    forecastCancel === null && forecastLate === null
      ? null
      : levelOf(forecastCancel ?? 0, forecastLate ?? 0);
  // A forecast of risk is true for its own blocks whatever the usual rate says of the others.
  if (forecast === 'delay' || forecast === 'cancel') return { level: forecast, answer: 'level' };
  // The usual rate never makes a level: "Low risk" would claim what no forecast said.
  if (anyUsual) return { level: null, answer: 'usual' };
  if (forecast === 'low') return { level: 'low', answer: 'level' };
  return { level: null, answer: 'none' };
}

/**
 * The three days of `entry` at an airport in `zone`, as of `now`: each block marked over once its
 * end has passed (a value the file still holds is never shown as current after that), and each
 * day's answer from the blocks left.
 */
export function dayViews(entry: FlightsAirportLive, zone: string, now: number): DayView[] {
  const wall = wallNow(zone, now);
  return [0, 1, 2].map((index) => {
    const day = addDays(entry.today, index);
    const cancelRow: FlightsBlockRow = entry.dep_canc[index] ?? [null, null, null, null, null];
    const lateRow: FlightsBlockRow = entry.dep_late[index] ?? [null, null, null, null, null];
    const cancelMask = entry.usual[0][index] ?? 0;
    const lateMask = entry.usual[1][index] ?? 0;
    const blocks: BlockValue[] = [];
    let cancel: number | null = null;
    let late: number | null = null;
    let forecastCancel: number | null = null;
    let forecastLate: number | null = null;
    let anyUsual = false;
    for (let i = 0; i < BLOCK_COUNT; i += 1) {
      const c = cancelRow[i] ?? null;
      const l = lateRow[i] ?? null;
      const cancelUsual = c !== null && bit(cancelMask, i);
      const lateUsual = l !== null && bit(lateMask, i);
      const over = blockOverAt(day, i, wall);
      blocks.push({
        cancel: c,
        late: l,
        cancelUsual,
        lateUsual,
        usual: cancelUsual || lateUsual,
        over,
      });
      if (over) continue;
      if (c !== null) {
        cancel = Math.max(cancel ?? 0, c);
        if (cancelUsual) anyUsual = true;
        else forecastCancel = Math.max(forecastCancel ?? 0, c);
      }
      if (l !== null) {
        late = Math.max(late ?? 0, l);
        if (lateUsual) anyUsual = true;
        else forecastLate = Math.max(forecastLate ?? 0, l);
      }
    }
    const { level, answer } = answerOf(forecastCancel, forecastLate, anyUsual);
    return { index, day, blocks, cancel, late, level, answer, usual: anyUsual };
  });
}

/** The day of `views` that is local today in the airport's zone, or null when the file has none. */
export function todayView(views: readonly DayView[], zone: string, now: number): DayView | null {
  const today = localToday(zone, now);
  return views.find((view) => view.day === today) ?? null;
}

/** A usual flight's two ends on one day, put together. */
export interface FlightChance {
  readonly departDay: LocalDate;
  readonly departBlock: number;
  readonly arriveDay: LocalDate;
  readonly arriveBlock: number;
  /** Minutes from leaving to landing, by the two clocks. */
  readonly minutes: number;
  readonly cancel: number | null;
  readonly late: number | null;
  /** The level, from forecast values only (answerOf); null where the answer is not a level. */
  readonly level: Level | null;
  readonly answer: DayAnswer;
  /** Whether a value it rests on is the usual rate. */
  readonly usual: boolean;
  /** Whether every value it rests on is the usual rate: no forecast for it at all. */
  readonly allUsual: boolean;
  /** Whether a value of each end is the usual rate. */
  readonly fromUsual: boolean;
  readonly toUsual: boolean;
  /**
   * Whether each end's cancel value is the usual rate: with both, the flight's cancel chance is
   * the usual rate whatever its late values are (LR-SF1), and is said so.
   */
  readonly fromCancelUsual: boolean;
  readonly toCancelUsual: boolean;
  /** Whether each end's late value is the usual rate. */
  readonly fromLateUsual: boolean;
  readonly toLateUsual: boolean;
  /**
   * How much of the cancel number is the usual rate (LR-SF8): 'all' with both ends' usual, 'part'
   * with one end's, 'none' with neither.
   */
  readonly cancelShare: UsualShare;
  /**
   * How much of the late number is the usual rate (LR-SF8). It is the larger end's value, so
   * 'all' where that end's is usual (or both are), 'part' where only the other end's is (or the
   * two are equal and one is usual), 'none' where neither is or there is no late number.
   */
  readonly lateShare: UsualShare;
}

/**
 * A flight row's pill and a grid cell (RoutePanel), which show the cancel number alone: how much
 * of that number is the usual rate, from its own two values (LR-SF8), and the level its color
 * shows. A number that is the usual rate in whole or in part has no level color; only a cancel
 * number that is wholly the forecast's takes the forecast's level, and a late value the pill does
 * not show never marks it usual.
 */
export function pillOf(chance: Pick<FlightChance, 'level' | 'cancelShare'>): {
  usual: UsualShare;
  level: Level | null;
} {
  if (chance.cancelShare !== 'none') return { usual: chance.cancelShare, level: null };
  return { usual: 'none', level: chance.level };
}

/** The late number's usual share: the larger end's value is the number (lateShare). */
function lateShareOf(
  dep: { readonly late: number | null; readonly lateUsual: boolean },
  arr: { readonly late: number | null; readonly lateUsual: boolean },
): UsualShare {
  if (dep.late === null || arr.late === null) return 'none';
  if (dep.lateUsual && arr.lateUsual) return 'all';
  if (!dep.lateUsual && !arr.lateUsual) return 'none';
  if (dep.late === arr.late) return 'part';
  const larger = dep.late > arr.late ? dep : arr;
  return larger.lateUsual ? 'all' : 'part';
}

interface End {
  readonly entry: FlightsAirportLive;
  readonly zone: string;
}

/** The values of `entry` for the block of local `day` and `block`, or nulls off its three days. */
function valueAt(
  entry: FlightsAirportLive,
  day: LocalDate,
  block: number,
  side: 'dep' | 'arr',
): { cancel: number | null; late: number | null; cancelUsual: boolean; lateUsual: boolean } {
  for (let index = 0; index < 3; index += 1) {
    if (addDays(entry.today, index) !== day) continue;
    const canc = side === 'dep' ? entry.dep_canc : entry.arr_canc;
    const late = side === 'dep' ? entry.dep_late : entry.arr_late;
    const target = side === 'dep' ? 0 : 2;
    const c = canc[index]?.[block] ?? null;
    const l = late[index]?.[block] ?? null;
    const cancelMask = entry.usual[target][index] ?? 0;
    const lateMask = entry.usual[(target + 1) as 1 | 3][index] ?? 0;
    return {
      cancel: c,
      late: l,
      cancelUsual: c !== null && bit(cancelMask, block),
      lateUsual: l !== null && bit(lateMask, block),
    };
  }
  return { cancel: null, late: null, cancelUsual: false, lateUsual: false };
}

/**
 * A flight that leaves `from` at local minute `leaves` on local `day` and lands at `to` at its
 * local minute `lands`: the departure block's chances at one end and the arrival block's at the
 * other. A cancel at either end cancels it (either); 45+ minutes late is the worse of the two
 * ends, since a late departure is most of a late arrival. With either end's value missing, the
 * flight has none.
 */
export function flightChance(
  from: End,
  to: End,
  day: LocalDate,
  leaves: number,
  lands: number,
): FlightChance {
  const departAt = instantOf(day, leaves, from.zone);
  let arriveAt = instantOf(day, lands, to.zone);
  while (arriveAt.getTime() <= departAt.getTime())
    arriveAt = new Date(arriveAt.getTime() + 86_400_000);
  while (arriveAt.getTime() - departAt.getTime() > 86_400_000)
    arriveAt = new Date(arriveAt.getTime() - 86_400_000);
  const departBlock = blockOfMinute(leaves);
  const departDay = departBlock.dayBefore ? addDays(day, -1) : day;
  const arriveLocal = localParts(arriveAt, to.zone);
  const arriveBlock = blockOfMinute(arriveLocal.minute);
  const arriveDay = arriveBlock.dayBefore ? addDays(arriveLocal.day, -1) : arriveLocal.day;
  const dep = valueAt(from.entry, departDay, departBlock.block, 'dep');
  const arr = valueAt(to.entry, arriveDay, arriveBlock.block, 'arr');
  const cancel = dep.cancel === null || arr.cancel === null ? null : either(dep.cancel, arr.cancel);
  const late = dep.late === null || arr.late === null ? null : Math.max(dep.late, arr.late);
  // The level comes from forecast values only: a usual end gives none (answerOf).
  const usual = dep.cancelUsual || dep.lateUsual || arr.cancelUsual || arr.lateUsual;
  const forecastCancels = [dep, arr].filter((end) => !end.cancelUsual && end.cancel !== null);
  const forecastLates = [dep, arr].filter((end) => !end.lateUsual && end.late !== null);
  const { level, answer } =
    cancel === null || late === null
      ? { level: null, answer: 'none' as const }
      : answerOf(
          forecastCancels.length === 0
            ? null
            : forecastCancels.reduce((sum, end) => either(sum, end.cancel ?? 0), 0),
          forecastLates.length === 0
            ? null
            : Math.max(...forecastLates.map((end) => end.late ?? 0)),
          usual,
        );
  return {
    departDay,
    departBlock: departBlock.block,
    arriveDay,
    arriveBlock: arriveBlock.block,
    minutes: Math.round((arriveAt.getTime() - departAt.getTime()) / 60_000),
    cancel,
    late,
    level,
    answer,
    usual,
    allUsual: dep.cancelUsual && dep.lateUsual && arr.cancelUsual && arr.lateUsual,
    fromUsual: dep.cancelUsual || dep.lateUsual,
    toUsual: arr.cancelUsual || arr.lateUsual,
    fromCancelUsual: dep.cancelUsual,
    toCancelUsual: arr.cancelUsual,
    fromLateUsual: dep.lateUsual,
    toLateUsual: arr.lateUsual,
    cancelShare:
      cancel === null
        ? 'none'
        : dep.cancelUsual && arr.cancelUsual
          ? 'all'
          : dep.cancelUsual || arr.cancelUsual
            ? 'part'
            : 'none',
    lateShare: lateShareOf(dep, arr),
  };
}

/**
 * The usual flights still to leave in each block of local `day` at an airport in `zone`, as of
 * `now`: a flight that leaves before 5 am counts in the night block of the day before, on the
 * weekday it really leaves (flights spec D11). The weights of an airport's day chance.
 */
export function blockCounts(
  flights: readonly { readonly leaves: number; readonly weekdays: number }[],
  day: LocalDate,
  zone: string,
  now: number,
): number[] {
  const counts = [0, 0, 0, 0, 0];
  const wall = wallNow(zone, now);
  const next = addDays(day, 1);
  for (const flight of flights) {
    const early = flight.leaves < BLOCK_STARTS[0];
    const on = early ? next : day;
    if ((flight.weekdays & (1 << weekdayIndex(on))) === 0) continue;
    if (Date.parse(`${on}T00:00:00Z`) + flight.leaves * 60_000 <= wall) continue;
    const { block } = blockOfMinute(flight.leaves);
    counts[block] = (counts[block] ?? 0) + 1;
  }
  return counts;
}

/** How much of what a number rests on is the usual rate. */
export type UsualShare = 'all' | 'part' | 'none';

function usualShare(flags: readonly boolean[]): UsualShare {
  if (flags.length > 0 && flags.every(Boolean)) return 'all';
  return flags.some(Boolean) ? 'part' : 'none';
}

/**
 * The big number an airport's day opens with (flights spec LR-F9), true for its label: the chance
 * a departure left in the day is cancelled, its blocks weighted by the usual flights still to
 * leave in each (`counts`, blockCounts); with no counts, or no usual flight left, the one value
 * every block left shares, or else the riskiest block's own chance with that block named.
 */
export interface DayHero {
  readonly cancel: number;
  /** The chance of leaving 45+ minutes late, for the same departures; null with none. */
  readonly late: number | null;
  /** The block the numbers are for; null for every departure left in the day. */
  readonly block: number | null;
  /** Whether part of the day has ended already. */
  readonly rest: boolean;
  readonly usual: UsualShare;
  /**
   * How much of the cancel number alone is the usual rate (LR-SF1): its headline keys on this,
   * so a usual cancel chance beside a forecast late chance is never said as a forecast.
   */
  readonly cancelUsual: UsualShare;
  /** How much of the late number alone is the usual rate ('none' with no late number). */
  readonly lateUsual: UsualShare;
}

export function dayHero(view: DayView, counts: readonly number[] | null): DayHero | null {
  const left = view.blocks
    .map((block, i) => ({ block, i }))
    .filter(({ block }) => !block.over && block.cancel !== null);
  if (left.length === 0) return null;
  const rest = view.blocks.some((block) => block.over);
  const weight = (i: number): number => counts?.[i] ?? 0;
  const total = left.reduce((sum, { i }) => sum + weight(i), 0);
  if (counts !== null && total > 0) {
    const used = left.filter(({ i }) => weight(i) > 0);
    const cancel = used.reduce((sum, { block, i }) => sum + (block.cancel ?? 0) * weight(i), 0);
    const lates = used.filter(({ block }) => block.late !== null);
    const lateTotal = lates.reduce((sum, { i }) => sum + weight(i), 0);
    const late = lates.reduce((sum, { block, i }) => sum + (block.late ?? 0) * weight(i), 0);
    return {
      cancel: Math.round(cancel / total),
      late: lateTotal > 0 ? Math.round(late / lateTotal) : null,
      block: null,
      rest,
      usual: usualShare(
        used.flatMap(({ block }) => [
          block.cancelUsual,
          ...(block.late === null ? [] : [block.lateUsual]),
        ]),
      ),
      cancelUsual: usualShare(used.map(({ block }) => block.cancelUsual)),
      lateUsual: usualShare(lates.map(({ block }) => block.lateUsual)),
    };
  }
  const first = left[0]?.block;
  const same =
    first !== undefined &&
    left.every(({ block }) => block.cancel === first.cancel && block.late === first.late);
  const picked = same
    ? null
    : left.reduce((a, b) =>
        (b.block.cancel ?? 0) > (a.block.cancel ?? 0) ||
        ((b.block.cancel ?? 0) === (a.block.cancel ?? 0) &&
          (b.block.late ?? 0) > (a.block.late ?? 0))
          ? b
          : a,
      );
  const shown = picked === null ? left : [picked];
  const block = (picked ?? left[0])?.block ?? first;
  return {
    cancel: block?.cancel ?? 0,
    late: block?.late ?? null,
    block: picked === null ? null : picked.i,
    rest,
    usual: usualShare(
      shown.flatMap(({ block: b }) => [b.cancelUsual, ...(b.late === null ? [] : [b.lateUsual])]),
    ),
    cancelUsual: usualShare(shown.map(({ block: b }) => b.cancelUsual)),
    lateUsual: usualShare(
      shown.filter(({ block: b }) => b.late !== null).map(({ block: b }) => b.lateUsual),
    ),
  };
}

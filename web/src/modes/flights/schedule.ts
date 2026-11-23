/**
 * The usual flights by day and time of day, and what Best time to fly may say of them (flights
 * spec D11, D13): pure functions over the routes and live files, as of `now`, so the panels and
 * their tests share one rule. A block that has ended is over; a flight that has left already is
 * never ranked or listed; the usual rate never names a time as safer than another.
 */
import { FlightsProgram } from '../../types/generated';
import type { FlightsAirportLive, FlightsUsualFlight, LocalDate } from '../../types/generated';
import {
  BLOCK_COUNT,
  BLOCK_STARTS,
  addDays,
  blockOver,
  flightChance,
  instantOf,
  levelOf,
  localToday,
  weekdayIndex,
  wholePercent,
} from './chance';
import type { FlightChance, Level } from './chance';
import { HOLDING, faaPrograms, programEnd, programEnded } from './data';
import type { LiveRead } from './data';

export interface Rated {
  readonly flight: FlightsUsualFlight;
  readonly chance: FlightChance;
  /** The local date it leaves: the day after its row's for one that leaves before 5 am. */
  readonly day: LocalDate;
}

/** A local minute in the order a day's blocks run: one before 5 am comes after the night's start. */
function inDayOrder(minute: number): number {
  return minute < BLOCK_STARTS[0] ? minute + 1440 : minute;
}

/** over: ended or every flight in it gone; none: no usual flight; noForecast: no value yet. */
export type CellState = 'over' | 'none' | 'noForecast' | 'value';

export interface Cell {
  readonly state: CellState;
  /** The flights still to leave, earliest first. */
  readonly flights: readonly Rated[];
  /** The safest of them with a chance. */
  readonly best: Rated | null;
}

export interface GridDay {
  readonly index: number;
  readonly date: LocalDate;
  readonly cells: readonly Cell[];
}

export interface End {
  readonly entry: FlightsAirportLive;
  readonly zone: string;
}

const RANK: Readonly<Record<Level, number>> = { low: 0, delay: 1, cancel: 2 };

/**
 * Best time to fly's order, from the numbers shown only (LR-F16.1, which replaces LR-F15.1's
 * order): the level they make (the higher of the cancel and the late level, each from its whole
 * percent), then the whole cancel percent, then the whole late percent. Two times that show the
 * same numbers compare equal, so neither is ever ranked over the other; the level first keeps a
 * Some risk time from being named the safest over a Low risk one (a 3% cancel with a 25% late one
 * is Some risk, a 4% cancel with a 24% late one is Low risk), and the line under the pick then
 * says why with both times' numbers (LR-F16.2).
 */
export function compareRated(a: Rated, b: Rated): number {
  const key = (rated: Rated): [number, number, number] => {
    const cancel = rated.chance.cancel ?? 0;
    const late = rated.chance.late ?? 0;
    return [RANK[levelOf(cancel, late)], wholePercent(cancel), wholePercent(late)];
  };
  const [a0, a1, a2] = key(a);
  const [b0, b1, b2] = key(b);
  return a0 - b0 || a1 - b1 || a2 - b2;
}

/** The next three local days at the origin from `today`, each with its usual flights by block. */
export function routeGrid(
  flights: readonly FlightsUsualFlight[],
  from: End,
  to: End,
  today: LocalDate,
  now: number,
): GridDay[] {
  return [0, 1, 2].map((index) => {
    const date = addDays(today, index);
    const next = addDays(date, 1);
    const all: Rated[][] = Array.from({ length: BLOCK_COUNT }, () => []);
    for (const flight of flights) {
      // One that leaves before 5 am is in this row's night, on the weekday it really leaves.
      const on = flight.leaves < BLOCK_STARTS[0] ? next : date;
      if ((flight.weekdays & (1 << weekdayIndex(on))) === 0) continue;
      const chance = flightChance(from, to, on, flight.leaves, flight.lands);
      if (chance.departDay !== date) continue;
      all[chance.departBlock]?.push({ flight, chance, day: on });
    }
    const cells: Cell[] = all.map((row, block) => {
      if (blockOver(date, block, from.zone, now)) return { state: 'over', flights: [], best: null };
      if (row.length === 0) return { state: 'none', flights: [], best: null };
      const left = row
        .filter((rated) => instantOf(rated.day, rated.flight.leaves, from.zone).getTime() > now)
        .sort((a, b) => inDayOrder(a.flight.leaves) - inDayOrder(b.flight.leaves));
      if (left.length === 0) return { state: 'over', flights: [], best: null };
      const rated = left.filter((r) => r.chance.cancel !== null && r.chance.late !== null);
      if (rated.length === 0) return { state: 'noForecast', flights: left, best: null };
      const best = rated.reduce((a, b) => (compareRated(b, a) < 0 ? b : a));
      return { state: 'value', flights: left, best };
    });
    return { index, date, cells };
  });
}

/** A route's grid cell and the row of its flights a flight was opened from (FlightsMode). */
export type { BackCell as RouteBack } from './address';

export interface Pick {
  readonly index: number;
  readonly date: LocalDate;
  readonly block: number;
}

/**
 * An FAA program that holds flights at one end of a route while the FAA read is live (LR-F14.3):
 * a ground stop, a ground delay program or a closed airport. `ends`: when it is set to end; with
 * no end given, the end of the origin's today row (5 am the next day there), since no one can say
 * when it lifts and the next day is a new read.
 */
export interface Hold {
  readonly code: string;
  readonly program: FlightsProgram;
  readonly ends: number;
  /**
   * Whether the end the FAA gave it has passed while the read is still live (data.ts
   * faaPrograms): it then holds only the times that start before that end, and is said as set to
   * end then, never as in place now (TRAV-R10-B3).
   */
  readonly ended: boolean;
}

/**
 * The holds at a route's two ends from `read` at `now` (origin first), by the one rule the FAA
 * lines use (data.ts faaPrograms): none unless its FAA part is live (under 30 minutes), so an old
 * read never moves Best time to fly; one past its stated end still holds the times that start
 * before that end, as the FAA lines say it was set to end then.
 */
export function faaHolds(
  read: LiveRead | null,
  ends: readonly { readonly code: string; readonly entry: FlightsAirportLive | null }[],
  originZone: string,
  now: number,
): Hold[] {
  const dayEnd = instantOf(
    addDays(localToday(originZone, now), 1),
    BLOCK_STARTS[0],
    originZone,
  ).getTime();
  const holds: Hold[] = [];
  for (const { code, entry } of ends)
    for (const program of faaPrograms(read, entry, now)) {
      if (!HOLDING.has(program.program)) continue;
      holds.push({
        code,
        program: program.program,
        ends: programEnd(program) ?? dayEnd,
        ended: programEnded(program, now),
      });
    }
  // In force before past its end, then the gravest first (a stop or a closed airport, then a
  // ground delay), the origin before the end.
  return holds.sort((a, b) => holdRank(a) - holdRank(b));
}

function holdRank(hold: Hold): number {
  return (hold.ended ? 2 : 0) + (hold.program === FlightsProgram.ground_delay ? 1 : 0);
}

/** Whether block `block` of origin `day` starts before a hold ends: a time it may hold. */
function heldBy(day: LocalDate, block: number, zone: string, holds: readonly Hold[]): boolean {
  if (holds.length === 0) return false;
  const starts = instantOf(day, BLOCK_STARTS[block] ?? 0, zone).getTime();
  return holds.some((hold) => starts < hold.ends);
}

/**
 * Every hold that may cover block `block` of origin `day`, in the holds' order (the gravest first):
 * none for a time no hold covers. Each one is named where the time is said held (TRAV-R12-S2, S3).
 */
export function holdsOn(
  day: LocalDate,
  block: number,
  faa: { readonly holds: readonly Hold[]; readonly zone: string } | undefined,
): Hold[] {
  if (faa === undefined) return [];
  return faa.holds.filter((hold) => heldBy(day, block, faa.zone, [hold]));
}

/**
 * What Best time to fly says (flights spec D11, LR-F9, LR-F14, LR-F15), from the shown numbers
 * only. `safest`: the lowest forecast cell no live hold covers (the earliest of equal ones), with
 * `best` one of its flights, even when it is one point under the next. `tie`: every such cell
 * shows the same whole cancel and late chance, so the line says the number (`held`: cells a hold
 * covers are left out of it). `faa`: a live FAA hold covers every forecast cell, so the line points
 * to the FAA, naming every hold that covers one (`holds`, the gravest first; TRAV-R13-S3). `usual`: every cell left rests on the usual rate, which never ranks one time over
 * another. `none`: no cell has a value. Usual cells are never ranked, and `usualDays` names the
 * days with no forecast at all (`usualSome` for usual cells on a day that has forecast ones too).
 * `todayHeld`: holds cover forecast times of today and the pick is a later day, so the line
 * under it says why today is not named, naming each hold (`all`: they cover every one left today).
 * `heldBy`: every hold that keeps a forecast time out, in the holds' order, so the lines name each
 * one and say whether each is past its stated end (TRAV-R12-S3). `passed`: under `safest`, the
 * open time with the lowest shown cancel chance when it is lower than the pick's (the earliest of
 * equal ones): passed over for its level, which only its higher late chance can make (LR-F16.2).
 */
export type BestTime =
  | {
      readonly kind: 'safest' | 'tie';
      readonly pick: Pick;
      readonly best: Rated;
      readonly usualDays: readonly LocalDate[];
      readonly usualSome: boolean;
      readonly held: boolean;
      readonly heldBy: readonly Hold[];
      readonly todayHeld: { readonly holds: readonly Hold[]; readonly all: boolean } | null;
      readonly passed: (Pick & { readonly best: Rated }) | null;
    }
  | { readonly kind: 'faa'; readonly holds: readonly Hold[] }
  | { readonly kind: 'usual' | 'none' };

export function bestTime(
  grid: readonly GridDay[],
  faa?: { readonly holds: readonly Hold[]; readonly zone: string },
): BestTime {
  const holds = faa?.holds ?? [];
  const cells: (Pick & { readonly best: Rated })[] = [];
  for (const row of grid)
    row.cells.forEach((cell, block) => {
      if (cell.best !== null)
        cells.push({ index: row.index, date: row.date, block, best: cell.best });
    });
  if (cells.length === 0) return { kind: 'none' };
  // The usual rate is no forecast: it never names one time as safer than another.
  const forecast = cells.filter((cell) => !cell.best.chance.usual);
  if (forecast.length === 0) return { kind: 'usual' };
  const usualDays = grid
    .filter(
      (row) =>
        row.cells.some((cell) => cell.best !== null) &&
        row.cells.every((cell) => cell.best === null || cell.best.chance.usual),
    )
    .map((row) => row.date);
  const usualSome = usualDays.length === 0 && cells.some((cell) => cell.best.chance.usual);
  // A time a live FAA hold may cover is never the safest (LR-F14.3).
  const holding = (cell: Pick): Hold[] => holdsOn(cell.date, cell.block, faa);
  const open = forecast.filter((cell) => holding(cell).length === 0);
  if (open.length === 0 && holds.length > 0)
    return {
      kind: 'faa',
      holds: holds.filter((h) => forecast.some((cell) => holding(cell).includes(h))),
    };
  // The lowest by the shown numbers, the earliest of equal ones: the cells run in the grid's order.
  const lowest = open.reduce((a, b) => (compareRated(b.best, a.best) < 0 ? b : a));
  const pick: Pick = { index: lowest.index, date: lowest.date, block: lowest.block };
  // A tie when every time it may name shows the same level and numbers (LR-F14.2, LR-F16.2).
  const same = open.length > 1 && open.every((cell) => compareRated(cell.best, lowest.best) === 0);
  /** Every hold that covers one of `list`, in the holds' own order (the gravest first). */
  const covering = (list: readonly Pick[]): Hold[] => {
    const found = new Set(list.flatMap(holding));
    return holds.filter((h) => found.has(h));
  };
  const today = forecast.filter((cell) => cell.index === 0);
  const todayHeldCells = today.filter((cell) => holding(cell).length > 0);
  const todayHeld =
    todayHeldCells.length === 0 || pick.index === 0
      ? null
      : { holds: covering(todayHeldCells), all: todayHeldCells.length === today.length };
  // The open time with the lowest whole cancel chance shown, when the pick shows more: passed over
  // for its level, which its chance of a long delay makes (LR-F16.2).
  const cancelOf = (cell: { readonly best: Rated }): number =>
    wholePercent(cell.best.chance.cancel ?? 0);
  const lowestCancel = open.reduce((a, b) => (cancelOf(b) < cancelOf(a) ? b : a));
  const passed = same || cancelOf(lowestCancel) >= cancelOf(lowest) ? null : lowestCancel;
  return {
    kind: same ? 'tie' : 'safest',
    pick,
    best: lowest.best,
    usualDays,
    usualSome,
    held: open.length < forecast.length,
    heldBy: covering(forecast),
    todayHeld,
    passed,
  };
}

/**
 * A flight number's legs from one airport: one per place it lands. BTS lists the same number
 * once per set of weekdays with its own times; those rows are one leg.
 */
export function flightLegs(rows: readonly FlightsUsualFlight[]): string[] {
  return [...new Set(rows.map((row) => row.to_airport))];
}

/** The row of leg `to` for `date`: the one whose weekdays hold it, else the one that flies most. */
export function rowForDay(
  rows: readonly FlightsUsualFlight[],
  to: string,
  date: LocalDate | null,
): FlightsUsualFlight | null {
  const leg = rows.filter((row) => row.to_airport === to);
  const weekday = date === null ? -1 : weekdayIndex(date);
  const onDay = leg.find((row) => weekday >= 0 && (row.weekdays & (1 << weekday)) !== 0);
  return onDay ?? [...leg].sort((a, b) => b.days - a.days)[0] ?? null;
}

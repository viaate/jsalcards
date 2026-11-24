/**
 * Backup plans (flights spec D18): the other ways to get there, ranked by a rough chance of
 * getting there with no cancel and no 45+ minute late arrival.
 *
 * The options, from the usual flights (D11) and the live block chances (FL-1's files):
 * 1. other flights of the same airline on the same route, that day and the day before;
 * 2. other airlines on the same route;
 * 3. nearby airports at either end: other covered airports within 120 miles in a straight line
 *    (said as "about N miles away", never a drive time);
 * 4. one stop through a different hub, when both legs usually fly that day with a 1 to 4 hour
 *    layover.
 * Each leg's chance is its own departure and arrival blocks (chance.ts flightChance), worked from
 * the whole percents the page shows (LR-F15.1); a plan's chance is its legs' chances multiplied.
 * With "I need to be there by", plans that land later are left out. Every plan is a usual flight
 * from a posted month: never a seat, a fare or a flight on sale, and never sure.
 *
 * Everything here runs in the browser from the published files; the Worker never does it (D18).
 * pipeline/snowlight/notify/flights_rules.py (backup_plans, rank_key) is the same rule for the
 * alerts, held to the same cases by its tests.
 */
import type {
  FlightsAirportLive,
  FlightsRoutes,
  FlightsUsualFlight,
  LocalDate,
} from '../../types/generated';
import { addDays, flightChance, instantOf, levelOf, weekdayIndex, wholePercent } from './chance';
import type { Level } from './chance';
import type { Airport } from './data';
import { BACKUP_LEAD_S, NEARBY_LEAD_S } from '../../copy-trips';

export const NEARBY_MILES = 120;
export const LAYOVER_MIN = 60;
export const LAYOVER_MAX = 240;
/** Hubs tried for one-stop plans: the busiest places the trip's airport usually flies to. */
export const HUBS_TRIED = 8;
/** Plans shown. */
export const MAX_PLANS = 6;
/** A plan this many points safer than the trip counts as safer (the alerts' SAFER_POINTS). */
export const SAFER_POINTS = 10;
/**
 * A backup is offered only when it leaves at least this long from now (ms): time to change the
 * ticket, get to the airport and through security. The alerts' own rule (copy-trips.ts
 * BACKUP_LEAD_S, flights_rules.py BACKUP_LEAD).
 */
export const BACKUP_LEAD = BACKUP_LEAD_S * 1000;
/** The same, for a backup that leaves from a nearby airport, a drive away (NEARBY_LEAD). */
export const NEARBY_LEAD = NEARBY_LEAD_S * 1000;

export type PlanKind = 'same' | 'other' | 'nearby' | 'hub';

export interface PlanLeg {
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  /** The local date it leaves, at `from`. */
  readonly day: LocalDate;
  readonly leaves: number;
  readonly lands: number;
  /** When it lands (ms). */
  readonly arrives: number;
  /** Whole percents shown. */
  readonly cancel: number;
  readonly late: number;
}

export interface Plan {
  readonly kind: PlanKind;
  readonly legs: readonly PlanLeg[];
  /** The rough chance of getting there with no cancel and no 45+ minute delay, whole percent. */
  readonly chance: number;
  /** Whether it leaves the day before the trip. */
  readonly dayBefore: boolean;
  /** For a nearby airport: the straight-line miles from the trip's airport at that end. */
  readonly miles: number | null;
}

export interface TripLike {
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  readonly day: LocalDate;
  readonly leaves: number;
  readonly lands: number;
  /** "I need to be there by", the arrival airport's local date and time, or null. */
  readonly needBy: string | null;
}

export interface PlanInputs {
  readonly trip: TripLike;
  readonly airports: ReadonlyMap<string, Airport>;
  /** Each airport's usual flights, as loaded (FlightsFiles.routes). */
  readonly routes: ReadonlyMap<string, FlightsRoutes | null>;
  readonly live: ReadonlyMap<string, FlightsAirportLive>;
  readonly now: number;
}

/** The straight-line distance in statute miles. */
export function miles(a: Pick<Airport, 'lat' | 'lon'>, b: Pick<Airport, 'lat' | 'lon'>): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The covered airports within NEARBY_MILES of `code`, nearest first (not `code` itself). */
export function nearby(
  airports: ReadonlyMap<string, Airport>,
  code: string,
): { code: string; miles: number }[] {
  const at = airports.get(code);
  if (at === undefined) return [];
  return [...airports.values()]
    .filter((airport) => airport.code !== code)
    .map((airport) => ({ code: airport.code, miles: miles(at, airport) }))
    .filter((row) => row.miles <= NEARBY_MILES)
    .sort((a, b) => a.miles - b.miles || a.code.localeCompare(b.code));
}

/** The newest posted month's usual flights from `code`, or none. */
function flightsFrom(inputs: PlanInputs, code: string): readonly FlightsUsualFlight[] {
  return inputs.routes.get(code)?.months[0]?.flights ?? [];
}

function fliesOn(flight: FlightsUsualFlight, day: LocalDate): boolean {
  return (flight.weekdays & (1 << weekdayIndex(day))) !== 0;
}

/** One usual flight on local `day`, scored, or null: gone, not that weekday, or no chance. */
export function legOf(
  inputs: PlanInputs,
  flight: FlightsUsualFlight,
  from: string,
  day: LocalDate,
): PlanLeg | null {
  if (!fliesOn(flight, day)) return null;
  const a = inputs.airports.get(from);
  const b = inputs.airports.get(flight.to_airport);
  const aLive = inputs.live.get(from);
  const bLive = inputs.live.get(flight.to_airport);
  if (a === undefined || b === undefined || aLive === undefined || bLive === undefined) return null;
  const leaves = instantOf(day, flight.leaves, a.tz).getTime();
  if (leaves <= inputs.now) return null;
  const chance = flightChance(
    { entry: aLive, zone: a.tz },
    { entry: bLive, zone: b.tz },
    day,
    flight.leaves,
    flight.lands,
  );
  if (chance.cancel === null || chance.late === null || chance.answer === 'none') return null;
  return {
    carrier: flight.carrier,
    number: flight.number,
    from,
    to: flight.to_airport,
    day,
    leaves: flight.leaves,
    lands: flight.lands,
    arrives: leaves + chance.minutes * 60_000,
    cancel: wholePercent(chance.cancel),
    late: wholePercent(chance.late),
  };
}

/** A leg's rough chance of going fine, from the shown whole percents: (1 - cancel)(1 - late). */
function legFine(leg: PlanLeg): number {
  return ((100 - leg.cancel) / 100) * ((100 - leg.late) / 100);
}

/** The plan's rough chance, in whole percent, never 100 (no plan is sure). */
export function planChance(legs: readonly PlanLeg[]): number {
  const fine = legs.reduce((product, leg) => product * legFine(leg), 1);
  return Math.min(99, Math.max(0, Math.round(fine * 100)));
}

/** The level a leg shows, the same words and color as the trip's (chance.ts levelOf). */
export function legLevel(leg: PlanLeg): Level {
  return levelOf(leg.cancel * 10, leg.late * 10);
}

/** The deadline as an instant, at the arrival airport's clock; null for none or one that does not read. */
export function deadline(needBy: string | null, zone: string | undefined): number | null {
  if (needBy === null || zone === undefined) return null;
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(needBy);
  if (match === null) return null;
  return instantOf(match[1] ?? '', Number(match[2]) * 60 + Number(match[3]), zone).getTime();
}

/** The trip's own flight, scored as a plan, or null where it has no chance (or has left). */
export function tripPlan(inputs: PlanInputs): Plan | null {
  const { trip } = inputs;
  const row = flightsFrom(inputs, trip.from).find(
    (f) => f.carrier === trip.carrier && f.number === trip.number && f.to_airport === trip.to,
  );
  const flight: FlightsUsualFlight = row ?? {
    carrier: trip.carrier,
    number: trip.number,
    to_airport: trip.to,
    leaves: trip.leaves,
    lands: trip.lands,
    weekdays: 127,
    days: 0,
    cancelled: 0,
    late: 0,
  };
  const leg = legOf(
    inputs,
    { ...flight, leaves: trip.leaves, lands: trip.lands, weekdays: 127 },
    trip.from,
    trip.day,
  );
  return leg === null
    ? null
    : { kind: 'same', legs: [leg], chance: planChance([leg]), dayBefore: false, miles: null };
}

function isTrip(trip: TripLike, leg: PlanLeg): boolean {
  return (
    leg.carrier === trip.carrier &&
    leg.number === trip.number &&
    leg.from === trip.from &&
    leg.day === trip.day
  );
}

const PLAN_ORDER: Record<PlanKind, number> = { same: 0, other: 1, nearby: 2, hub: 3 };

/**
 * The order of the plans (flights_rules.py rank_key, D11): the plans at least SAFER_POINTS safer
 * than the trip come first, the same airline and route first among them (that day or the day
 * before), then other airlines, nearby airports and one stop, each by chance; then the rest by
 * chance. Ties: the one that lands first, then the kind, then the flights.
 */
export function rankPlans(plans: readonly Plan[], tripChance: number | null): Plan[] {
  const safer = (plan: Plan): boolean =>
    tripChance !== null && plan.chance >= tripChance + SAFER_POINTS;
  return [...plans].sort((a, b) => {
    const aSafer = safer(a);
    const bSafer = safer(b);
    if (aSafer !== bSafer) return aSafer ? -1 : 1;
    return (
      (aSafer ? PLAN_ORDER[a.kind] - PLAN_ORDER[b.kind] : 0) ||
      b.chance - a.chance ||
      (a.legs.at(-1)?.arrives ?? 0) - (b.legs.at(-1)?.arrives ?? 0) ||
      PLAN_ORDER[a.kind] - PLAN_ORDER[b.kind] ||
      planKey(a).localeCompare(planKey(b))
    );
  });
}

/**
 * The plans for a trip in rankPlans' order: the safer ones first, the same airline first among
 * them. Plans that land after the deadline are left out.
 */
export function backupPlans(inputs: PlanInputs): Plan[] {
  const { trip } = inputs;
  const plans: Plan[] = [];
  const add = (
    kind: PlanKind,
    legs: PlanLeg[],
    dayBefore: boolean,
    distance: number | null,
  ): void => {
    plans.push({ kind, legs, chance: planChance(legs), dayBefore, miles: distance });
  };
  const days: [LocalDate, boolean][] = [
    [trip.day, false],
    [addDays(trip.day, -1), true],
  ];
  // 1 and 2: the same route, that day and the day before.
  for (const [day, before] of days) {
    for (const flight of flightsFrom(inputs, trip.from)) {
      if (flight.to_airport !== trip.to) continue;
      const leg = legOf(inputs, flight, trip.from, day);
      if (leg === null || isTrip(trip, leg)) continue;
      add(flight.carrier === trip.carrier ? 'same' : 'other', [leg], before, null);
    }
  }
  // 3: nearby airports at either end, that day.
  const starts = [{ code: trip.from, miles: 0 }, ...nearby(inputs.airports, trip.from)];
  const ends = new Map([
    [trip.to, 0],
    ...nearby(inputs.airports, trip.to).map((row) => [row.code, row.miles] as const),
  ]);
  for (const start of starts) {
    for (const flight of flightsFrom(inputs, start.code)) {
      const endMiles = ends.get(flight.to_airport);
      if (endMiles === undefined) continue;
      if (start.code === trip.from && flight.to_airport === trip.to) continue;
      const leg = legOf(inputs, flight, start.code, trip.day);
      if (leg === null) continue;
      add('nearby', [leg], false, Math.max(start.miles, endMiles));
    }
  }
  // 4: one stop through a hub, both legs that day, a 1 to 4 hour layover.
  for (const hub of hubsFor(inputs)) {
    for (const first of flightsFrom(inputs, trip.from)) {
      if (first.to_airport !== hub) continue;
      const one = legOf(inputs, first, trip.from, trip.day);
      if (one === null) continue;
      const hubAirport = inputs.airports.get(hub);
      if (hubAirport === undefined) continue;
      for (const second of flightsFrom(inputs, hub)) {
        if (second.to_airport !== trip.to) continue;
        // The second leg's local day at the hub: the day the first one lands there.
        for (const day of [trip.day, addDays(trip.day, 1)]) {
          const two = legOf(inputs, second, hub, day);
          if (two === null) continue;
          const departs = instantOf(day, second.leaves, hubAirport.tz).getTime();
          const layover = (departs - one.arrives) / 60_000;
          if (layover < LAYOVER_MIN || layover > LAYOVER_MAX) continue;
          add('hub', [one, two], false, null);
        }
      }
    }
  }
  const due = deadline(trip.needBy, inputs.airports.get(trip.to)?.tz);
  const kept = plans.filter(
    (plan) =>
      (due === null || (plan.legs.at(-1)?.arrives ?? Infinity) <= due) && catchable(inputs, plan),
  );
  const ranked = rankPlans(kept, tripPlan(inputs)?.chance ?? null);
  // One row per set of flights (a flight both nearby and on the route is said once).
  const seen = new Set<string>();
  return ranked.filter((plan) => {
    const key = planKey(plan);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Whether the plan's first flight leaves late enough to change to it and get there. */
function catchable(inputs: PlanInputs, plan: Plan): boolean {
  const first = plan.legs[0];
  const zone = first === undefined ? undefined : inputs.airports.get(first.from)?.tz;
  if (first === undefined || zone === undefined) return false;
  const lead = first.from === inputs.trip.from ? BACKUP_LEAD : NEARBY_LEAD;
  return instantOf(first.day, first.leaves, zone).getTime() >= inputs.now + lead;
}

function planKey(plan: Plan): string {
  return plan.legs
    .map((leg) => `${leg.carrier}${String(leg.number)}-${leg.from}-${leg.day}`)
    .join('+');
}

/** The hubs tried: the busiest places the trip's airport usually flies to, not either end. */
export function hubsFor(inputs: {
  readonly trip: Pick<TripLike, 'from' | 'to'>;
  readonly airports: PlanInputs['airports'];
  readonly routes: PlanInputs['routes'];
}): string[] {
  const { trip } = inputs;
  const codes = new Set(
    (inputs.routes.get(trip.from)?.months[0]?.flights ?? []).map((f) => f.to_airport),
  );
  return [...codes]
    .filter((code) => code !== trip.to && code !== trip.from)
    .map((code) => inputs.airports.get(code))
    .filter((airport): airport is Airport => airport !== undefined)
    .sort((a, b) => b.perDay - a.perDay || a.code.localeCompare(b.code))
    .slice(0, HUBS_TRIED)
    .map((airport) => airport.code);
}

/** The airports whose usual flights the plans need: the trip's ends, those nearby, and the hubs. */
export function airportsNeeded(inputs: {
  readonly trip: Pick<TripLike, 'from' | 'to'>;
  readonly airports: PlanInputs['airports'];
  readonly routes: PlanInputs['routes'];
}): string[] {
  const { trip } = inputs;
  const codes = new Set([trip.from, ...nearby(inputs.airports, trip.from).map((row) => row.code)]);
  if (inputs.routes.has(trip.from)) for (const hub of hubsFor(inputs)) codes.add(hub);
  return [...codes];
}

/** Whether a trip looks risky enough to lead with its backup plans (D18): some or high risk. */
export function looksRisky(plan: Plan | null): boolean {
  const leg = plan?.legs[0];
  return leg !== undefined && legLevel(leg) !== 'low';
}

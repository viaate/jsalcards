/**
 * The words of Flights mode (flights spec D17), held to the same house
 * style as copy.ts (scripts/check-copy.mjs reads this file as copy): short sentences, no hedges,
 * no exclamation marks, no em dashes. It loads with Flights mode, never in the page's first script.
 *
 * Codes are written the way people say them: MCI, WN 1234.
 */

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

/** The five parts of a day an airport's chances are given for, as the files order them. */
export const BLOCK_KEYS = ['early', 'morning', 'afternoon', 'evening', 'night'] as const;
export type BlockKey = (typeof BLOCK_KEYS)[number];

/** How much risk a chance means (modes/flights/chance.ts levelOf). */
export type LevelKey = 'low' | 'delay' | 'cancel';

export const flightsCopy = /* @__PURE__ */ deepFreeze({
  search: {
    /** Shorter than Schools' own, so the field it takes the place of stays the page's largest text. */
    placeholder: 'Airport, flight or route',
    label: 'Search an airport, flight or route',
    results: 'Search results',
    none: 'No airport, flight or route found',
    clear: 'Clear search',
    sections: { airport: 'Airports', route: 'Routes', flight: 'Flights' },
    /** Under a flight number typed with no airport yet. */
    flightNeedsAirport: 'Add the airport it leaves from',
  },
  menu: {
    label: 'Flights menu',
    storms: 'Past storms',
    record: 'How our flight chances did',
  },
  /**
   * The rows under an answer (LR-F18.2): a label on the left and its value on the right, in the
   * same style as Schools' detail rows, never free sentences of their own sizes.
   */
  facts: {
    late: 'Delay of 45+ min',
    counts: 'Counts',
    bothAirports: 'Both airports',
    /** The FAA's label at the airport the panel names. */
    faa: 'FAA',
    faaStatus: 'FAA status',
    usualTimes: 'Usual times',
    /** Times whose chance is the usual rate in whole or in part: never ranked (LR-SF8). */
    usualNotRanked: 'Usual rate in them, not ranked',
    forecast: 'Forecast',
    noneThisDay: 'None for this day yet',
    usualRate: 'Usual rate',
    /**
     * Which numbers shown are the usual rate (LR-SF8), by the cancel number's share then the
     * delay number's: each short enough to sit on one line beside its label at 360 px.
     */
    usualWhich: {
      all_none: 'Cancel chance',
      part_none: 'Part of the cancel chance',
      none_all: 'Delay chance',
      none_part: 'Part of the delay chance',
      all_all: 'Both chances',
      part_part: 'Part of both chances',
      all_part: 'Cancel chance, part of delay',
      part_all: 'Delay chance, part of cancel',
    },
    /** The forecast's weather beside a usual cancel chance: never said as its reason. */
    weather: 'Weather',
    /**
     * The record beside a usual cancel chance (LR-SF1): past days, never a forecast. Each row
     * stays on one line beside its label at 360 px, so the kind names the days in the label.
     */
    cancelledHere: 'Cancelled here',
    otherAirports: 'Elsewhere',
    leftOut: 'Left out',
    weatherAndFaa: 'Weather and the FAA',
    today: 'Today',
    partOfToday: 'Part of today',
    heldByHolds: 'Held by FAA holds',
    notNamedYet: 'Not named until the next FAA update',
  },
  legend: {
    label: 'Chance of cancels and long delays today',
    low: 'Low risk',
    delay: 'Some risk',
    cancel: 'High risk',
    usual: 'Usual rate',
    /** The key while the file is old: the map then shows every airport gray, at no risk. */
    old: 'The map is old, so it shows no risk now.',
  },
  /** The status pill and the answer card, by level. */
  level: {
    low: 'Low risk',
    delay: 'Some risk of delay',
    cancel: 'High risk of cancel',
  },
  blocks: {
    early: 'Early',
    morning: 'Morning',
    afternoon: 'Afternoon',
    evening: 'Evening',
    night: 'Night',
  },
  blockHours: {
    early: '5 to 9 am',
    morning: '9 am to noon',
    afternoon: 'Noon to 5 pm',
    evening: '5 to 9 pm',
    night: '9 pm to 5 am',
  },
  today: 'Today',
  tomorrow: 'Tomorrow',
  /** The day chips' group, for a screen reader. */
  dayGroup: 'Day',
  /** The shared map, while Flights shows (Schools' own is copy.map.label). */
  mapLabel: 'Map of airports and their flight chances',
  cancel: 'Cancel',
  late: '45+ min late',
  /** A part of the day that is over, or that no forecast covers. */
  over: 'Over',
  noForecast: 'No forecast',
  /** Beside a value that is the usual rate, not a forecast. */
  usualMark: 'Usual',
  /** Under a table with a usual value: true whether no run was read or the gate failed here. */
  usualNote: 'Usual means the usual rate for this time of year, in place of our forecast.',
  /**
   * Under a usual chance, where no forecast chance covers the day: the weather forecast may still
   * name snow below, so it says which forecast is missing.
   */
  noForecastDay: 'No forecast chance for this day yet.',
  /** The headline after midnight, when only the day before's night block is left. */
  nightLeft: 'Chance of a cancel from now to 5 am',
  /** An airport's day with no value left. */
  noValueLeft: 'No forecast for the rest of this day.',
  close: 'Close',
  back: 'Back',
  faa: {
    title: 'FAA now',
    /** Over a read past its limit or none at all: never "now" over what is not now's. */
    titleOld: 'FAA',
    ground_stop: 'Ground stop',
    ground_delay: 'Ground delay',
    departure_delay: 'Departure delays',
    arrival_delay: 'Arrival delays',
    closed: 'Airport closed',
    deicing: 'Deicing',
    none: 'No FAA delays',
    /**
     * On a flight's card for a day after today: the FAA's state is now's alone. Said only while
     * the read is live (faaDayNote); past its limit, the Old line, which never says "now".
     */
    notThatDay: 'This is the FAA now, not on the day of this flight.',
    notThatDayOld: 'This is the last status from the FAA, not on the day of this flight.',
    /** On an airport's own panel for a day after today, the same way. */
    notThisDay: 'This is the FAA now, not on this day.',
    notThisDayOld: 'This is the last status from the FAA, not on this day.',
    notRead: 'We could not read the FAA status just now.',
    /** The FAA's kind of reason, on a line of its own; none for its "other". */
    why: {
      weather: 'Because of weather.',
      volume: 'Because of heavy traffic.',
      equipment: 'Because of an equipment problem.',
      runway: 'Because of runway work.',
    },
  },
  alerts: {
    title: 'Weather alerts',
    winter_storm: 'Winter storm',
    blizzard: 'Blizzard',
    ice_storm: 'Ice storm',
    winter_weather: 'Winter weather',
    severe_thunderstorm: 'Severe storms',
    tornado: 'Tornado',
    high_wind: 'High wind',
    dense_fog: 'Dense fog',
    hurricane: 'Hurricane',
    tropical_storm: 'Tropical storm',
    extreme_cold: 'Extreme cold',
  },
  why: {
    title: 'Why',
    /** The reasons' heading under a usual cancel chance: the forecast's weather, never its why. */
    forecastTitle: 'In the forecast',
    snow: 'Snow in the forecast',
    ice: 'Freezing rain in the forecast',
    thunder: 'Thunderstorms in the forecast',
    wind: 'Strong wind in the forecast',
    fog: 'Low clouds or fog in the forecast',
    cold: 'Deep cold in the forecast',
    hubs: 'Storms at big hubs',
    before: 'A storm the day before',
    calm: 'No storm in the forecast',
  },
  record: {
    title: 'In bad weather',
    kinds: {
      freezing_rain: 'Freezing rain',
      snow: 'Snow',
      thunder: 'Thunderstorms',
      fog: 'Low clouds and fog',
      wind: 'Strong wind',
    },
    /**
     * Past days of each kind, in the words of the forecast's reasons and the kinds above, one word
     * per weather (LR-SF8 rule 6): "Windy days here" | "49 since 2020"; "Freezing rain days".
     */
    pastKinds: {
      freezing_rain: 'Freezing rain days',
      snow: 'Snowy days',
      thunder: 'Thunderstorm days',
      fog: 'Foggy days',
      wind: 'Windy days',
    },
    sooner: 'Cancels sooner than most',
    longer: 'Holds out longer than most',
    notReady: 'This airport’s record is not ready yet.',
  },
  route: {
    title: 'Best time to fly',
    noFlights: 'No nonstop flights usually fly this route.',
    /** Over the hubs a route with no nonstop flights usually connects through (D13). */
    hubs: 'No nonstop flights usually fly this route. Its flights usually connect at one of these airports. Here is the chance of a cancel at each one today.',
    hubsNone: 'We could not find an airport that usually connects this route.',
    none: 'No usual flights',
    /** The same, in a grid cell. */
    noneShort: 'No flights',
    /** Best time to fly when no time can be named the safest. */
    /**
     * Every time left rests on the usual rate in whole or in part (LR-SF8): one line, and the rows
     * under it say which numbers.
     */
    allUsual: 'The usual rate is in each chance here, so none of these times stands out.',
    /** Beside forecast cells, usual ones on the same days: never ranked. */
    usualSome: 'Times with the usual mark have no forecast yet, so they are not ranked.',
    noForecast: 'We have no forecast for these days yet.',
    /** Under a grid with a cell that has no number: said once, for every such cell. */
    noForecastNote: 'No forecast means we have no number for that time yet.',
    /** Under a grid where a time's color comes from its chance of a long delay (TRAV-R11-S2). */
    lateNote:
      'A time can show more risk than its cancel chance when its chance of a long delay is high.',
    pick: 'Pick a time to see its flights',
    notReady: 'The usual flights are not ready yet.',
  },
  flight: {
    title: 'Flight',
    left: 'Its usual time today has passed. See tomorrow.',
    /** Not in the flights that usually fly from here, and no regional flight has its number. */
    notFound: 'We could not find this flight in the flights that usually fly from here.',
    notThatDay: 'It does not usually fly this day.',
    notReady: 'The usual flights are not ready yet.',
    storms: 'This flight on past storm days',
  },
  waiver: {
    /** The card of the airlines' free-change waivers (its link names the airline's own page). */
    title: 'Travel waivers',
    noneAtAirport: 'No airline has posted a waiver here for these days yet.',
    notCheckedAtAirport: 'We could not check the airlines’ pages just now.',
  },
  storms: {
    title: 'Past storms',
    pastDay: 'Past day',
    /** A held-out day from before Flights began (D14): what the chances would have said. */
    said: 'Our chance',
    /** Said once above the table, so its narrow column's head stays short. */
    /** The rows under a past storm's number (LR-F18.2). */
    ourChance: 'Our chance',
    usualRate: 'Usual rate',
    madeAt: 'Made',
    eveningBefore: 'The evening before',
    thisDay: 'This day',
    happened: 'What happened',
    keptOut: 'Kept out when our chances were made',
    testYear: 'From the test year, kept out of our chances',
    none: 'No past storms yet.',
    notReady: 'Past storms are not ready yet.',
  },
  track: {
    title: 'How our flight chances did',
    notReady: 'Our record is not ready yet.',
    targets: {
      dep_canc: 'Cancels at departure',
      dep_late: '45+ min late at departure',
      arr_canc: 'Cancels at arrival',
      arr_late: '45+ min late at arrival',
      rough: 'Rough days',
    },
    months: 'Months scored',
    noMonths: 'No month scored yet.',
  },
  live: {
    notRead: 'We could not read the flight chances just now.',
    /** Only while the first read is out; once it has failed, notRead (liveWait). */
    loading: 'Reading flight chances',
  },
  airport: 'Airport',
  /** Airlines by code, as people say them; a code not here is shown as its code. */
  airlines: {
    AA: 'American',
    AS: 'Alaska',
    B6: 'JetBlue',
    DL: 'Delta',
    F9: 'Frontier',
    G4: 'Allegiant',
    HA: 'Hawaiian',
    MX: 'Breeze',
    NK: 'Spirit',
    UA: 'United',
    WN: 'Southwest',
    // Regional airlines, which fly under a bigger airline's name (REGIONAL_AIRLINES); one whose
    // name is not one plain word has none here, and the line of regional airlines leaves it out
    // (regionalNames), never showing a bare code.
    '9E': 'Endeavor',
    C5: 'CommuteAir',
    G7: 'GoJet',
    MQ: 'Envoy',
    OO: 'SkyWest',
    PT: 'Piedmont',
    QX: 'Horizon',
    YV: 'Mesa',
    YX: 'Republic',
  },
  /** The rough day chance's line, where the file has one (flights spec D6). */
  roughNote: 'A rough day is one with 1 in 10 flights or more cancelled.',
  /** Opens an airport's own panel from a flight. */
  openAirport: 'See this airport',
});

// Formatters ------------------------------------------------------------------------------

/** A per mille value as a whole percent: "4%", "Under 1%". */
export function percent(perMille: number): string {
  const whole = Math.round(perMille / 10);
  if (whole < 1) return 'Under 1%';
  return `${String(whole)}%`;
}

/** An age in minutes, short: "4 min", "2 h", "3 days". */
export function age(minutes: number): string {
  const m = Math.max(0, Math.floor(minutes));
  if (m < 60) return `${String(m)} min`;
  const hours = Math.floor(m / 60);
  if (hours < 48) return `${String(hours)} h`;
  return `${String(Math.floor(hours / 24))} days`;
}

/** The update line: "Updated 4 min ago", or, past its freshness limit, "Old: from 3 h ago". */
export function updated(minutes: number, stale: boolean): string {
  return stale ? `Old: from ${age(minutes)} ago` : `Updated ${age(minutes)} ago`;
}

/** An FAA line's age, past which it is never shown as live. */
export function faaAge(minutes: number, stale: boolean): string {
  return stale ? `FAA status from ${age(minutes)} ago` : `Updated ${age(minutes)} ago`;
}

/** A minute of the day as a clock time: "5:05 am", "12:30 pm". */
export function clock(minute: number): string {
  const m = ((Math.round(minute) % 1440) + 1440) % 1440;
  const hours = Math.floor(m / 60);
  const minutes = m % 60;
  const half = hours < 12 ? 'am' : 'pm';
  const shown = hours % 12 === 0 ? 12 : hours % 12;
  return `${String(shown)}:${String(minutes).padStart(2, '0')} ${half}`;
}

/** A local date (YYYY-MM-DD) as "Mon, Nov 24". */
export function shortDate(day: string): string {
  return new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${day}T12:00:00Z`));
}

/** A local date as "Jan 5, 2025". */
export function longDate(day: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${day}T12:00:00Z`));
}

/** A local date as its weekday: "Monday". */
export function weekday(day: string): string {
  return new Intl.DateTimeFormat('en-US', { weekday: 'long', timeZone: 'UTC' }).format(
    new Date(`${day}T12:00:00Z`),
  );
}

/** A posted month (YYYY-MM) as "Sep 2026". */
export function monthName(month: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${month}-15T12:00:00Z`));
}

/** `day` less `today`, in whole days (both local dates). */
function daysFrom(today: string, day: string): number {
  return Math.round(
    (Date.parse(`${day}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) / 86_400_000,
  );
}

/**
 * The name of the day a column is for, from the local date now (`today`) at its airport: Today,
 * Tomorrow, then the weekday. A day before today (the night that runs past midnight) and every
 * day of an old file are named by their dates, never as today.
 */
export function dayName(day: string, today: string, stale = false): string {
  const ahead = stale ? -1 : daysFrom(today, day);
  if (ahead === 0) return flightsCopy.today;
  if (ahead === 1) return flightsCopy.tomorrow;
  if (ahead > 1 && ahead < 7) return weekday(day);
  return shortDate(day);
}

/** The day in a sentence: "today", "tomorrow", "on Tuesday", "on Sat, Nov 21". */
export function dayWords(day: string, today: string): string {
  const ahead = daysFrom(today, day);
  if (ahead === 0) return 'today';
  if (ahead === 1) return 'tomorrow';
  if (ahead > 1 && ahead < 7) return `on ${weekday(day)}`;
  return `on ${shortDate(day)}`;
}

/** A time zone's short name on a day: "CST". */
export function zoneName(zone: string, at: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'short' })
    .formatToParts(at)
    .find((part) => part.type === 'timeZoneName');
  return parts?.value ?? '';
}

/** "WN 1234". */
export function flightName(carrier: string, number: number): string {
  return `${carrier} ${String(number)}`;
}

/** "MCI to LAX". */
export function routeName(from: string, to: string): string {
  return `${from} to ${to}`;
}

/** The rough day chance: "Rough day chance: 8%.", or "Usual rough day chance: 3%." */
export function roughLine(perMille: number, usual: boolean): string {
  return `${usual ? 'Usual rough day chance' : 'Rough day chance'}: ${percent(perMille).toLowerCase()}.`;
}

// The answer's big number and its lines, as Schools' panel gives its chance (LR-F9) -------------

/** The big digits, without their sign: "4", or "<1" below one percent, as Schools' do. */
export function heroNumber(perMille: number): string {
  const whole = Math.round(perMille / 10);
  return whole < 1 ? '<1' : String(whole);
}

/** The day in a headline: "today", "tomorrow", "Tuesday", "Sat, Nov 21". */
export function chanceWhen(day: string, today: string): string {
  const ahead = daysFrom(today, day);
  if (ahead === 0) return 'today';
  if (ahead === 1) return 'tomorrow';
  if (ahead > 1 && ahead < 7) return weekday(day);
  return shortDate(day);
}

/**
 * "Chance of a cancel today", or once part of the day has ended, words true for what is left:
 * "... for the rest of today", or after midnight, when only the day before's night is left,
 * "Chance of a cancel from now to 5 am". Never a past day's name over part of it.
 */
export function dayChance(day: string, today: string, rest: boolean): string {
  const ahead = daysFrom(today, day);
  if (ahead < 0) return flightsCopy.nightLeft;
  if (rest && ahead === 0) return 'Chance of a cancel for the rest of today';
  return `Chance of a cancel ${chanceWhen(day, today)}`;
}

/** One block's chance: "Chance of a cancel today, 5 to 9 pm"; the night left: from now. */
export function blockChance(day: string, today: string, block: BlockKey): string {
  if (daysFrom(today, day) < 0) return flightsCopy.nightLeft;
  return `Chance of a cancel ${chanceWhen(day, today)}, ${hoursIn(block)}`;
}

/**
 * The usual rate as itself: "Usual chance of a cancel on a Sunday", with its block's hours;
 * `restOfToday`, a day number over the blocks left today: "... for the rest of today".
 */
export function usualChance(day: string, block: BlockKey | null, restOfToday = false): string {
  if (block === null && restOfToday) return 'Usual chance of a cancel for the rest of today';
  const hours = block === null ? '' : `, ${hoursIn(block)}`;
  return `Usual chance of a cancel on a ${weekday(day)}${hours}`;
}

/** A row under an answer (LR-F18.2): its label on the left, its value on the right. */
export interface Fact {
  readonly label: string;
  readonly value: string;
}

/** The row under a chance for its long delay: "Delay of 45+ min" | "8%". */
export function lateFact(perMille: number): Fact {
  return { label: flightsCopy.facts.late, value: percent(perMille) };
}

/** The row for an FAA read 30 minutes old or more: "FAA status" | "From 40 min ago". */
export function faaOldFact(minutes: number): Fact {
  return { label: flightsCopy.facts.faaStatus, value: `From ${age(minutes)} ago` };
}

/** The row that says the chance is for the whole flight: "Counts" | "Both airports". */
export function bothFact(): Fact {
  return { label: flightsCopy.facts.counts, value: flightsCopy.facts.bothAirports };
}

/** The row for the forecast's reason: "Why" | "Snow in the forecast". */
export function whyFact(reason: string): Fact {
  return { label: flightsCopy.why.title, value: reason };
}

/** A time in Best time to fly: its day and its block. */
interface Time {
  readonly day: string;
  readonly block: BlockKey;
}

/**
 * Best time to fly's headline over the safest cell's number, in two short sentences (D17,
 * LR-F17.1): what the number is with its day and time, then that it is the safest, "Chance of a
 * cancel tomorrow, 9 am to noon. It is the safest time to fly." `scoped`: some times have no
 * forecast and are not ranked, so the claim is the safest of the times with one.
 */
export function safestChance(pick: Time, today: string, scoped = false): string {
  return `${blockChance(pick.day, today, pick.block)}. It is the safest time ${scoped ? 'with a forecast' : 'to fly'}.`;
}

/** An FAA hold by its program and airport. */
interface HoldWords {
  readonly program: number;
  readonly code: string;
}

/**
 * Best time to fly when every forecast time it may name shows the same numbers (LR-F14.2,
 * LR-F15.1), with the number: "Every time shows the same chance: 2%." `scoped`: usual times beside
 * them are not counted, "Every time with a forecast ...". `held`: times a live FAA hold covers are
 * not counted either, said in a short sentence of its own (D17, LR-F17.1): "It leaves out times
 * with an FAA hold." `after`: the holds behind `held` when every one of them is past the end the
 * FAA gave it, which are never said as in force now (TRAV-R11-B1): "It leaves out times before the
 * FAA hold was set to end." The FAA rows under it name each hold with its stated end.
 */
export function sameChance(
  perMille: number,
  scoped = false,
  held = false,
  after: readonly HoldWords[] = [],
): string {
  const every = `Every time${scoped ? ' with a forecast' : ''} shows the same chance: ${percent(perMille).toLowerCase()}.`;
  if (!held) return every;
  const left =
    after.length === 0
      ? 'It leaves out times with an FAA hold.'
      : after.length === 1
        ? 'It leaves out times before the FAA hold was set to end.'
        : 'It leaves out times before the FAA holds were set to end.';
  return `${every} ${left}`;
}

/** A time's shown numbers in Best time to fly: its cancel and late chance. */
interface Shown {
  readonly cancel: number;
  /** null: no late chance to show. */
  readonly late: number | null;
}

/**
 * The row under Best time to fly's pick when an open time with a lower cancel chance is passed
 * over for its level (LR-F16.2, LR-F18.2): the time, then its shown numbers, "Early tomorrow" |
 * "3% cancel, 25% delay". The grid's colors already show each time's level.
 */
export function passedFact(day: string, today: string, block: BlockKey, passed: Shown): Fact {
  const when = blockWhen(block, safestDay(day, today));
  const cancel = `${percent(passed.cancel)} cancel`;
  return {
    label: `${when.charAt(0).toUpperCase()}${when.slice(1)}`,
    value: passed.late === null ? cancel : `${cancel}, ${percent(passed.late).toLowerCase()} delay`,
  };
}

/** An FAA program as the hold it is, in a sentence: "the FAA ground stop at MCI". */
function holdName(program: number, code: string): string {
  const key = PROGRAM_KEYS[program];
  if (key === 'closed') return `the closing of ${code}`;
  return `the FAA ${key === 'ground_delay' ? 'ground delay' : 'ground stop'} at ${code}`;
}

/** An FAA hold as Best time to fly's lines name it: with its stated end once that has passed. */
interface HoldSaid extends HoldWords {
  /** The clock time it was set to end at, once that has passed; null while it is in force. */
  readonly endedAt: string | null;
}

/**
 * The row under Best time to fly's pick on a later day, when FAA holds cover today's times
 * (LR-F15.3a): why today is not named. `all`: they cover every time left today with a forecast.
 * A lone hold in force by name, "Today" | "Held by the FAA ground stop at MCI"; more in force, "Held
 * by FAA holds", which the FAA rows name each of (TRAV-R13-S3). With every hold past the end the
 * FAA gave it, never said as holding now (TRAV-R11-B1): "Not named until the next FAA update".
 */
export function heldTodayFact(holds: readonly HoldSaid[], all: boolean): Fact {
  const label = all ? flightsCopy.facts.today : flightsCopy.facts.partOfToday;
  const live = holds.filter((hold) => hold.endedAt === null);
  const [only] = live;
  if (only === undefined) return { label, value: flightsCopy.facts.notNamedYet };
  if (live.length > 1) return { label, value: flightsCopy.facts.heldByHolds };
  return { label, value: `Held by ${holdName(only.program, only.code)}` };
}

/**
 * A held cell's words for a screen reader, after its chance (TRAV-R12-S2), kept short (TRAV-R13-S4):
 * a lone hold by name, as the lines say it: ", held by the FAA ground stop at MCI"; one past its
 * stated end, which the lines say it was set to end then: ", not named for the FAA ground stop at
 * MCI", never said as holding now. Two or more in a few words, which the lines under the answer
 * name: ", held by FAA holds", or with each past its end, ", not named for FAA holds".
 */
export function cellHeld(holds: readonly HoldSaid[]): string {
  const [only] = holds;
  if (only === undefined) return '';
  const live = holds.some((hold) => hold.endedAt === null);
  if (holds.length > 1) return live ? ', held by FAA holds' : ', not named for FAA holds';
  if (only.endedAt === null) return `, held by ${holdName(only.program, only.code)}`;
  return `, not named for ${holdName(only.program, only.code)}`;
}

/**
 * A clock time at another airport than the one the panel's times are in (TRAV-R11-S4): "5:00 pm
 * LAX time".
 */
export function clockAt(time: string, code: string): string {
  return `${time} ${code} time`;
}

/**
 * Best time to fly when live FAA holds cover every time with a forecast (LR-F14.3): it points to
 * the FAA, and no time is named the safest. A lone hold by name: "The FAA has a ground stop at MCI
 * now. Check back when it ends."; one past the end the FAA gave it is said as set to end then,
 * never as now (TRAV-R10-B3). Two or more together, in short sentences (LR-F17.1), with the FAA
 * rows under it naming each (TRAV-R13-S3): "FAA holds cover every time now. Check back when they
 * end."; with any past its stated end, never "now": "FAA holds cover every time. Check back for
 * the next FAA update."
 */
export function faaWait(holds: readonly HoldSaid[]): string {
  const [only] = holds;
  if (only === undefined) return '';
  if (holds.length === 1) return faaWaitOne(only.program, only.code, only.endedAt);
  return holds.every((hold) => hold.endedAt === null)
    ? 'FAA holds cover every time now. Check back when they end.'
    : 'FAA holds cover every time. Check back for the next FAA update.';
}

/** faaWait for a lone hold. */
function faaWaitOne(program: number, code: string, endedAt: string | null): string {
  // Past the end the FAA gave it: said as set to end then, never as now (TRAV-R10-B3).
  if (endedAt !== null)
    return `${faaEndedLine(program, code, endedAt)} Check back for the next FAA update.`;
  if (PROGRAM_KEYS[program] === 'closed') return `${code} is closed now. Check back when it opens.`;
  const what = PROGRAM_KEYS[program] === 'ground_delay' ? 'a ground delay' : 'a ground stop';
  return `The FAA has ${what} at ${code} now. Check back when it ends.`;
}

/** The heading over a Best time to fly cell's flights: "Tuesday afternoon: what usually flies, from Sep 2026". */
export function cellFlights(day: string, today: string, block: BlockKey, month: string): string {
  const when = blockWhen(block, safestDay(day, today));
  return `${when.charAt(0).toUpperCase()}${when.slice(1)}: what usually flies, from ${monthName(month)}`;
}

/** A row's chance: its number only (in gray under an old file), never a level said as a sentence. */
export function cancelAnswer(cancel: number): string {
  return `Cancel chance ${percent(cancel).toLowerCase()}.`;
}

/** A flight that is not found, where a regional flight from here has its number. */
export function regionalMatch(
  airline: string,
  flight: string,
  from: string,
  to: string,
  leaves: string,
): string {
  return `${airline} flies ${flight} from ${from} to ${to} at ${leaves} for bigger airlines. Is this your flight?`;
}

/**
 * Under it: regional flights carry their own airline's code (LR-F10.3), with the same number:
 * "Flights run by regional airlines are listed under their own codes, like OO 5489 for SkyWest."
 */
export function notFoundRegional(flight: string, airline: string): string {
  return `Flights run by regional airlines are listed under their own codes, like ${flight} for ${airline}.`;
}

/** A flight number not found here: "We could not find DL 5489 from MCI in the flights that usually fly." */
export function notFoundAt(flight: string, from: string): string {
  return `We could not find ${flight} from ${from} in the flights that usually fly.`;
}

/**
 * The FAA's live program at an airport, as a row under a Flights answer (LR-F9, LR-F18.2):
 * "FAA at MCI" | "Ground stop now". `counted`: the answer above shows a chance, which LR-F4 keeps
 * the FAA out of, so the row says so, short enough for one line at 360 px: "Ground stop now, not
 * counted". `code` null: the
 * airport the panel names already (LR-F9: the title's code is never said again), "FAA".
 */
export function faaFact(program: number, code: string | null, counted = false): Fact | null {
  const key = PROGRAM_KEYS[program];
  if (key === undefined) return null;
  const now: Readonly<Record<FaaKey, string>> = {
    ground_stop: 'Ground stop now',
    ground_delay: 'Ground delay now',
    departure_delay: 'Departures late now',
    arrival_delay: 'Arrivals late now',
    closed: 'Closed now',
    deicing: 'Deicing now',
  };
  return {
    label: faaLabel(code),
    // After the value under a chance, which never counts the FAA (LR-F4).
    value: counted ? `${now[key]}, not counted` : now[key],
  };
}

/** An FAA row's label: "FAA at MCI", or "FAA" at the airport the panel names. */
function faaLabel(code: string | null): string {
  return code === null ? flightsCopy.facts.faa : `${flightsCopy.facts.faa} at ${code}`;
}

/**
 * The FAA's program past the end it gave it, as a row (TRAV-R10-B3): never said as in place now,
 * only as set to end then, since the next read says whether it did: "FAA at MCI" | "Ground stop was
 * set to end at 7:06 pm".
 */
export function faaEndedFact(program: number, code: string | null, time: string): Fact {
  const key = PROGRAM_KEYS[program];
  if (key === 'closed') return { label: faaLabel(code), value: `Was set to open at ${time}` };
  const name = key === undefined ? 'FAA delay' : PROGRAM_THE[key].replace(/^The /, '');
  const value = `${name.charAt(0).toUpperCase()}${name.slice(1)} was set to end at ${time}`;
  return { label: faaLabel(code), value };
}

/**
 * The FAA's program past the end it gave it, with the read still live (TRAV-R10-B3): never said as
 * in place now, only as set to end then, since the next read says whether it did: "The ground stop
 * at MCI was set to end at 7:06 pm." `code` null: "here". `counted`: as faaHeroLine.
 */
export function faaEndedLine(program: number, code: string | null, time: string): string {
  const key = PROGRAM_KEYS[program];
  const where = code === null ? 'here' : `at ${code}`;
  const line =
    key === 'closed'
      ? `${code ?? 'This airport'} was set to open at ${time}.`
      : `${key === undefined ? 'The FAA delay' : PROGRAM_THE[key]} ${where} was set to end at ${time}.`;
  return line;
}

/** Each FAA program with its article, inside a sentence. */
const PROGRAM_THE: Readonly<Record<Exclude<FaaKey, 'closed'>, string>> = {
  ground_stop: 'The ground stop',
  ground_delay: 'The ground delay',
  departure_delay: 'The departure delay',
  arrival_delay: 'The arrival delay',
  deicing: 'Deicing',
};

/** How much of a number is the usual rate (chance.ts UsualShare). */
type Share = 'all' | 'part' | 'none';

/**
 * The row for days whose times rest on the usual rate, in whole or in part, beside forecast ones:
 * "Tuesday" | "Usual rate in them, not ranked" (LR-SF8: one form, whatever their share).
 */
export function usualDaysFact(days: readonly string[], today: string): Fact {
  return {
    label: listOf(days.map((day) => dayName(day, today))),
    value: flightsCopy.facts.usualNotRanked,
  };
}

/**
 * The row for times with the usual rate in them beside forecast ones on the same days: "Usual
 * times" | "Usual rate in them, not ranked". Never "no forecast": where a run was read and its test
 * failed, there is one, and it is not used.
 */
export function usualSomeFact(): Fact {
  return { label: flightsCopy.facts.usualTimes, value: flightsCopy.facts.usualNotRanked };
}

/** What the numbers shown rest on, for the rows under them (LR-SF8). */
export interface UsualShown {
  /** How much of the cancel number is the usual rate, from its own values. */
  readonly cancel: Share;
  /** How much of the delay number is the usual rate; null where no delay number shows. */
  readonly late: Share | null;
  /** Whether a forecast run was read for the day: with none, the forecast is not there yet. */
  readonly run: boolean;
  /** The airports with no run read for the day, all of whose values are the usual rate. */
  readonly codes?: readonly string[];
  /** The forecast's weather: said as the weather, never as the reason for a usual number. */
  readonly reason?: string | null;
  /** The airport the weather is at, named on a flight: "At LAX". */
  readonly reasonAt?: string | null;
}

/**
 * The rows under numbers shown where any is the usual rate in whole or in part (LR-SF8): exactly
 * one "Usual rate" | <which> row ("Cancel chance", "Delay chance", "Both chances", "Part of the
 * delay chance", ...) and one "Left out" | "Weather and the FAA" row, the same rows whatever the
 * combination; with none usual, no rows at all (the panel says its forecast's reason as "Why").
 * Then, where no forecast was read, one "Forecast" row: "Not ready for MCI and LAX" with the
 * airports known, else, with every number shown wholly usual, "None for this day yet" (a number
 * from the forecast means one was read). Then the forecast's weather, never said as the
 * reason for the usual rate: "Weather" | "Strong wind in the forecast", or "At LAX" with
 * `reasonAt`, short so the longest reason fits on its line at 360 px.
 */
export function usualFacts(shown: UsualShown): Fact[] {
  const { facts } = flightsCopy;
  const which = `${shown.cancel}_${shown.late ?? 'none'}` as const;
  if (which === 'none_none') return [];
  const codes = shown.codes ?? [];
  const allUsual = shown.cancel === 'all' && (shown.late === null || shown.late === 'all');
  const reason = shown.reason ?? null;
  const at = shown.reasonAt ?? null;
  const forecast: Fact[] =
    codes.length > 0
      ? [{ label: facts.forecast, value: `Not ready for ${listOf(codes)}` }]
      : shown.run || !allUsual
        ? []
        : [{ label: facts.forecast, value: facts.noneThisDay }];
  return [
    { label: facts.usualRate, value: facts.usualWhich[which] },
    { label: facts.leftOut, value: facts.weatherAndFaa },
    ...forecast,
    ...(reason === null
      ? []
      : [{ label: at === null ? facts.weather : `At ${at}`, value: reason }]),
  ];
}

/**
 * A hub's chance today: "Chance of a cancel today: 4%", "Usual chance of a cancel today: 1%";
 * with `block`, the one time it is of, named: "Chance of a cancel this evening: 9%".
 */
export function hubChance(
  perMille: number,
  usual: boolean | Share,
  block: BlockKey | null = null,
): string {
  const share = shareOf(usual);
  const when = block === null ? 'today' : blockWhen(block, 'today');
  const said = percent(perMille).toLowerCase();
  if (share === 'part') return `Chance of a cancel ${when}, usual in part: ${said}`;
  return `${share === 'all' ? 'Usual chance' : 'Chance'} of a cancel ${when}: ${said}`;
}

/** A share from a flag: true is the usual rate as a whole, false none of it. */
function shareOf(usual: boolean | Share): Share {
  return usual === true ? 'all' : usual === false ? 'none' : usual;
}

/**
 * The usual mark's note, naming the airports: "... in place of our forecast for MCI and LAX."
 * True whether no run was read there or the airport's own test failed.
 */
export function usualNoteFor(codes: readonly string[]): string {
  return `Usual means the usual rate for this time of year, in place of our forecast for ${listOf(codes)}.`;
}

/** The same note on a past day. */
export function usualNotePast(code: string): string {
  return `Usual means the usual rate for that time of year, in place of our forecast for ${code}.`;
}

/** Regional airlines at an airport, which fly under bigger airlines' names. */
export function regionalLine(names: readonly string[]): string {
  return `${listOf(names)} ${names.length === 1 ? 'flies' : 'fly'} here for bigger airlines. For those flights, check the waiver of the airline on your ticket.`;
}

/**
 * A flight's pill whose cancel chance is the usual rate: "Usual rate. Cancel chance 1%."; in part
 * (`part`, one end's usual rate and the other's forecast): "Usual in part. Cancel chance 9%."
 */
export function usualAnswer(cancel: number, part = false): string {
  return `${part ? 'Usual in part' : 'Usual rate'}. Cancel chance ${percent(cancel).toLowerCase()}.`;
}

/** "this morning", "tonight", "early tomorrow", "Monday afternoon". */
function blockWhen(block: BlockKey, dayName: string): string {
  if (dayName === 'today') {
    const today: Readonly<Record<BlockKey, string>> = {
      early: 'early today',
      morning: 'this morning',
      afternoon: 'this afternoon',
      evening: 'this evening',
      night: 'tonight',
    };
    return today[block];
  }
  return block === 'early' ? `early ${dayName}` : `${dayName} ${block}`;
}

/** The day for safestChance(): "today", "tomorrow", or the weekday. */
export function safestDay(day: string, today: string): string {
  const ahead = daysFrom(today, day);
  return ahead === 0 ? 'today' : ahead === 1 ? 'tomorrow' : weekday(day);
}

/** A screen reader's line for one block of an airport's day. */
export function blockLine(block: BlockKey, cancel: string, late: string): string {
  return `${flightsCopy.blocks[block]}, ${hoursIn(block)}. Cancel: ${cancel}. 45+ min late: ${late}.`;
}

/**
 * A value for blockLine: "3%", "3%, usual", and with the level its color shows, so the level is
 * never told by color alone (LR-F15.2): "30%, high risk".
 */
export function valueWords(
  perMille: number,
  usual: boolean,
  level: LevelKey | null = null,
): string {
  if (usual) return `${percent(perMille)}, ${flightsCopy.usualMark.toLowerCase()}`;
  return level === null
    ? percent(perMille)
    : `${percent(perMille)}, ${flightsCopy.legend[level].toLowerCase()}`;
}

/** A hub with no chance today. */
export function hubNone(): string {
  return 'No forecast today.';
}

/**
 * A Best time to fly cell for a screen reader: "Tomorrow, Morning: 2% chance of a cancel, usual";
 * on an old file, each cell says so with its age, as the grid's gray does: "... Old: from 1 h ago".
 */
export function cellLabel(
  day: string,
  block: BlockKey,
  words: string,
  old: string | null = null,
): string {
  return `${day}, ${flightsCopy.blocks[block]}: ${words}${old === null ? '' : `. ${old}`}`;
}

/**
 * A cell's value for a screen reader, with what it measures and the level its color shows, so the
 * level is never told by color alone (LR-F15.2): "5% chance of a cancel, some risk"; a usual value
 * has no level: "2% chance of a cancel, usual", or in part: "9% chance of a cancel, usual in part".
 */
export function cellChance(
  perMille: number,
  usual: boolean | Share,
  level: LevelKey | null = null,
  fromLate = false,
): string {
  const chance = `${percent(perMille)} chance of a cancel`;
  const share = shareOf(usual);
  if (share === 'all') return `${chance}, ${flightsCopy.usualMark.toLowerCase()}`;
  if (share === 'part') return `${chance}, ${flightsCopy.usualMark.toLowerCase()} in part`;
  if (level === null) return chance;
  // A level its cancel chance alone would not make: from the chance of a long delay, said so.
  const word = flightsCopy.legend[level].toLowerCase();
  return `${chance}, ${fromLate ? `${word} of a long delay` : word}`;
}

/** A hub's line on a route with no nonstop flights: "DEN, Denver: Low risk today." */
export function hubLine(code: string, city: string, answer: string): string {
  return `${code}, ${city}: ${answer}`;
}

/** Where a flight's past storm days are not in our files yet: the airport's record stands in. */
export function stormsFallback(code: string): string {
  return `We do not have this flight on past storm days yet. Here is how ${code} does in bad weather.`;
}

/** Under a flight card's times: "Usual times from Sep 2026". */
export function usualTimes(month: string): string {
  return `Usual times from ${monthName(month)}`;
}

/** The usual flights' label: "What usually flies, from Sep 2026". */
export function usualFrom(month: string): string {
  return `What usually flies, from ${monthName(month)}`;
}

/** A record line with its verdict or its plain numbers. */
export function recordLine(share: number, others: number, days: number): string {
  return `${percent(share)} cancelled on ${String(days)} such days. Other airports: ${percent(others).toLowerCase()}.`;
}

/**
 * The record kind (records/<code>.json, KIND_KEYS) a forecast reason (REASON_KEYS) speaks to:
 * snow, ice as freezing rain, thunder, wind, fog; null for cold, hubs and a storm the day before.
 */
export function reasonKind(reason: number): number | null {
  return REASON_KINDS[reason] ?? null;
}

const REASON_KINDS: Readonly<Record<number, number | undefined>> = { 0: 2, 1: 1, 2: 3, 3: 5, 4: 4 };

/**
 * The record beside a usual cancel chance (flights-demo-honesty, LR-SF1): what past days of this
 * weather did here, as past days, never a forecast. `line`: the record's line for the kind, null
 * with no record read (then nothing is said); `first`: the record's first day; `code`: the
 * airport, named where the panel is not that airport's own. "Windy days here" | "60 since
 * 2020", "Cancelled here" | "5% in the wind", "Elsewhere" | "7% in the same weather" ("Windy
 * days at LAX", "Cancelled at LAX" with `code`). Each row fits on one line at 360 px. The share
 * is of departures in the hours of that weather only (schemas/flights.py share), never of whole
 * days, so it says so: "in the wind". The days are the record's own count
 * (schemas/flights.py days): days with a block of this weather here and a peer airport in the
 * same weather, the days its shares are from.
 * Its bad days (days with any one block of this weather 10% cancelled) are not said: in words
 * they read as whole days 10% cancelled, which they are not.
 */
export function notInUsual(
  kind: number,
  line: { days: number; share: number; others: number } | null,
  first: string,
  code: string | null = null,
): Fact[] {
  const key = KIND_KEYS[kind];
  if (key === undefined || line === null) return [];
  const { facts } = flightsCopy;
  const kinds = flightsCopy.record.pastKinds[key];
  const label = code === null ? `${kinds} here` : `${kinds} at ${code}`;
  const year = first.slice(0, 4);
  if (line.days <= 0) return [{ label, value: `None since ${year}` }];
  return [
    { label, value: `${String(line.days)} since ${year}` },
    {
      label: code === null ? facts.cancelledHere : `Cancelled at ${code}`,
      value: `${percent(line.share)} ${PAST_IN[key]}`,
    },
    { label: facts.otherAirports, value: `${percent(line.others)} in the same weather` },
  ];
}

/**
 * The track record's line where its scores are not for the chances the live file shows
 * (LR-SF2): dated, and nothing it would contradict. "These scores are from Nov 22, 2026. They
 * are not for the chances on the map now, so we do not show them."
 */
export function trackNotShown(generatedAt: string): string {
  return `These scores are from ${longDate(generatedAt.slice(0, 10))}. They are not for the chances on the map now, so we do not show them.`;
}

/** The record's span: "Since 2015". */
export function recordSince(first: string): string {
  return `Since ${first.slice(0, 4)}, bad weather days only.`;
}

/**
 * An FAA program's line: "Ground delay, about 45 min"; past the end the FAA gave it, with the read
 * still live, that end instead: "Ground stop, set to end at 7:06 pm" (TRAV-R10-B3).
 */
export function programLine(
  name: string,
  minutes: number | null,
  endedAt: string | null = null,
): string {
  if (endedAt !== null) return `${name}, set to end at ${endedAt}`;
  return minutes === null ? name : `${name}, about ${String(minutes)} min`;
}

/** A search result's kind. */
export function sectionName(kind: 'airport' | 'route' | 'flight'): string {
  return flightsCopy.search.sections[kind];
}

/** "Until 8:00 pm". */
export function until(minute: number): string {
  return `Until ${clock(minute)}`;
}

/** W2's three states, word for word (waivers spec W2). */
export function waiverFound(airline: string, code: string, day: string, minutes: number): string {
  return `${airline} posted a free-change waiver for ${code} on ${shortDay(day)}. Checked ${age(minutes)} ago.`;
}

export function waiverNone(airline: string, code: string, day: string, minutes: number): string {
  return `No waiver on ${airline}’s page for ${code} on ${shortDay(day)} yet. Checked ${age(minutes)} ago.`;
}

export function waiverNotChecked(airline: string): string {
  return `We could not check ${airline}’s page just now.`;
}

/**
 * The unclear state (the waivers lane's LR-W1): a waiver that does not plainly say it covers this
 * airport or day. The ruling's words with its "may" put plainly, as the house style asks.
 */
export function waiverUnclear(airline: string, minutes: number): string {
  return `${airline} posted a travel waiver. We could not tell if it covers this trip. Check ${airline}’s page. Checked ${age(minutes)} ago.`;
}

/** Several airlines at one airport with none found: "Delta and United have no waiver ...". */
export function waiverNoneMany(
  airlines: readonly string[],
  code: string,
  day: string,
  minutes: number,
): string {
  return `${listOf(airlines)} ${airlines.length === 1 ? 'has' : 'have'} no waiver for ${code} on ${shortDay(day)} yet. Checked ${age(minutes)} ago.`;
}

/** Several airlines whose pages could not be read. */
export function waiverNotCheckedMany(airlines: readonly string[]): string {
  return airlines.length === 1
    ? waiverNotChecked(airlines[0] ?? '')
    : `We could not check these airlines’ pages just now: ${listOf(airlines)}.`;
}

/** "Delta", "Delta and United", "Delta, United and American". */
function listOf(names: readonly string[], joiner: 'and' | 'or' = 'and'): string {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} ${joiner} ${names[names.length - 1] ?? ''}`;
}

/** "Jan 5". */
function shortDay(day: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${day}T12:00:00Z`));
}

/** A past storm's title: "MCI, Jan 5, 2025". */
export function stormTitle(code: string, day: string): string {
  return `${code}, ${longDate(day)}`;
}

/** A past storm's number's line: "Of flights cancelled on Jan 5, 2025", a past day by its date. */
export function stormCancelled(day: string): string {
  return `Of flights cancelled on ${longDate(day)}`;
}

/**
 * The rows under a past storm's number (LR-F18.2): what our chances would have said the evening
 * before, on a held-out day from before Flights began, "Our chance" | "15% for a rough day" and
 * "Made" | "The evening before", or, where the airport's chance had not passed its test and the
 * day showed the usual rate, "Usual rate" | "15% for a rough day"; then why the day could be
 * tested, "This day" | "Kept out when our chances were made".
 */
export function stormFacts(said: number, usual: boolean, apart: number): Fact[] {
  const { storms } = flightsCopy;
  return [
    {
      label: usual ? storms.usualRate : storms.ourChance,
      value: `${percent(said)} for a rough day`,
    },
    ...(usual ? [] : [{ label: storms.madeAt, value: storms.eveningBefore }]),
    { label: storms.thisDay, value: apart === 1 ? storms.keptOut : storms.testYear },
  ];
}

/** A past storm's row: "100% cancelled". */
export function cancelledWords(perMille: number): string {
  return `${percent(perMille)} cancelled`;
}

/** A past storm's row for a screen reader: "Past day. MCI, Jan 5, 2025. 100% cancelled." */
export function stormRowLabel(title: string, share: string): string {
  return `${flightsCopy.storms.pastDay}. ${title}. ${share}.`;
}

/** "12 of 40 cancelled". */
export function cancelledOf(cancelled: number, departures: number): string {
  return `${String(cancelled)} of ${String(departures)} cancelled`;
}

/** The test year's span: "Tested on Oct 1, 2025 to Sep 30, 2026, days never used to make them." */
export function testSpan(first: string, last: string): string {
  return `Tested on ${longDate(first)} to ${longDate(last)}, days never used to make them.`;
}

/**
 * A target's skill: "Beat the usual rate by 12%. Passed the test at 40 of 359 airports." The
 * count is the test's, never the map's now: an airport that passed can still show the usual rate
 * when its observations are not fresh.
 */
export function skillLine(skill: number, published: number, tested: number): string {
  const whole = Math.round(skill * 100);
  const beat =
    whole > 0 ? `Beat the usual rate by ${String(whole)}%` : 'Did not beat the usual rate';
  return `${beat}. Passed the test at ${String(published)} of ${String(tested)} airports.`;
}

/** A scored month: "Sep 2026: 30 of 30 days scored, 3 rough days, 2 caught." */
export function monthLine(
  month: string,
  scored: number,
  days: number,
  rough: number,
  caught: number,
): string {
  return `${monthName(month)}: ${String(scored)} of ${String(days)} days scored, ${String(rough)} rough days, ${String(caught)} caught.`;
}

// Names of the files' coded values (schemas/flights-live.schema.json) --------------------------

type FaaKey =
  'ground_stop' | 'ground_delay' | 'departure_delay' | 'arrival_delay' | 'closed' | 'deicing';
const PROGRAM_KEYS: readonly (FaaKey | undefined)[] = [
  'ground_stop',
  'ground_delay',
  'departure_delay',
  'arrival_delay',
  'closed',
  'deicing',
];
const PROGRAM_WHY_KEYS: readonly (keyof typeof flightsCopy.faa.why | undefined)[] = [
  undefined,
  'weather',
  'volume',
  'equipment',
  'runway',
];
const ALERT_KEYS: readonly (Exclude<keyof typeof flightsCopy.alerts, 'title'> | undefined)[] = [
  'winter_storm',
  'blizzard',
  'ice_storm',
  'winter_weather',
  'severe_thunderstorm',
  'tornado',
  'high_wind',
  'dense_fog',
  'hurricane',
  'tropical_storm',
  'extreme_cold',
];
const REASON_KEYS: readonly (
  Exclude<keyof typeof flightsCopy.why, 'title' | 'forecastTitle' | 'calm'> | undefined
)[] = ['snow', 'ice', 'thunder', 'wind', 'fog', 'cold', 'hubs', 'before'];
/**
 * The hours a record's share is of: its departures in the blocks of that weather only, never
 * whole days (schemas/flights.py), as "5% in the wind".
 */
const PAST_IN: Readonly<Record<keyof typeof flightsCopy.record.kinds, string>> = {
  freezing_rain: 'in freezing rain',
  snow: 'in the snow',
  thunder: 'in thunderstorms',
  fog: 'in the fog',
  wind: 'in the wind',
};
const KIND_KEYS: readonly (keyof typeof flightsCopy.record.kinds | undefined)[] = [
  undefined,
  'freezing_rain',
  'snow',
  'thunder',
  'fog',
  'wind',
];

/** An FAA program by its code: "Ground stop"; null for a code this build does not know. */
export function programName(code: number): string | null {
  const key = PROGRAM_KEYS[code];
  return key === undefined ? null : flightsCopy.faa[key];
}

/** The FAA's kind of reason by its code, on a line of its own; null for "other" or unknown. */
export function programWhy(code: number): string | null {
  const key = PROGRAM_WHY_KEYS[code];
  return key === undefined ? null : flightsCopy.faa.why[key];
}

/** An NWS alert by its code: "Winter storm". */
export function alertName(code: number): string | null {
  const key = ALERT_KEYS[code];
  return key === undefined ? null : flightsCopy.alerts[key];
}

/** A plain reason in the forecast by its code: "Snow in the forecast". */
export function reasonName(code: number): string | null {
  const key = REASON_KEYS[code];
  return key === undefined ? null : flightsCopy.why[key];
}

/** A weather kind of the own record by its code: "Freezing rain". */
export function kindName(code: number): string | null {
  const key = KIND_KEYS[code];
  return key === undefined ? null : flightsCopy.record.kinds[key];
}

/** An airline as people say it, by its code: "Delta"; its code where this build has no name. */
/** The regional airlines of `codes` that have a name, by name: none shown as a bare code. */
export function regionalNames(codes: readonly string[]): string[] {
  const names: Readonly<Record<string, string | undefined>> = flightsCopy.airlines;
  return codes.flatMap((code) => {
    const name = names[code];
    return name === undefined ? [] : [name];
  });
}

/** A block's hours inside a sentence: "today, noon to 5 pm", never "today, Noon to 5 pm". */
function hoursIn(block: BlockKey): string {
  const hours = flightsCopy.blockHours[block];
  return hours.charAt(0).toLowerCase() + hours.slice(1);
}

/** The link to an airline's own travel alerts page: "Delta travel alerts". */
export function airlineAlerts(airline: string): string {
  return `${airline} travel alerts`;
}

export function airlineName(code: string): string {
  const names: Readonly<Record<string, string | undefined>> = flightsCopy.airlines;
  return names[code] ?? code;
}

/**
 * The line under an FAA card for a day after today, by how the FAA was read: "now" only while
 * the read is live; past its limit, its last status, never called now; none with no read at all
 * (the card says it could not read it). `where`: a flight's card or an airport's own panel.
 */
export function faaDayNote(
  read: 'live' | 'old' | 'none',
  where: 'flight' | 'airport',
): string | null {
  if (read === 'none') return null;
  const faa = flightsCopy.faa;
  if (where === 'flight') return read === 'live' ? faa.notThatDay : faa.notThatDayOld;
  return read === 'live' ? faa.notThisDay : faa.notThisDayOld;
}

/** What a panel says while it has no live file: reading, or, once the read has failed, so. */
export function liveWait(failed: boolean): string {
  return failed ? flightsCopy.live.notRead : flightsCopy.live.loading;
}

/** Airport codes joined for one line: "MCI and LAX", or with `or`: "MCI or LAX". */
export function codesOf(codes: readonly string[], or = false): string {
  if (codes.length <= 1) return codes[0] ?? '';
  return `${codes.slice(0, -1).join(', ')} ${or ? 'or' : 'and'} ${codes[codes.length - 1] ?? ''}`;
}

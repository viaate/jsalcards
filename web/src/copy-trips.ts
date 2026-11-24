/**
 * The words of Flights trips (flights spec D12, D18, D19, D20 W8): My trips, the ticket type tap,
 * Backup plans, Connect Google, the Flights alerts and their email. Part of Flights' copy
 * (scripts/check-copy.mjs reads it as copy): short sentences, no hedges, no exclamation marks, no
 * em dashes. Its only import is copy-flights.ts, which imports nothing, so the push worker and
 * the accounts API (the alert email) use these same words.
 */
import {
  airlineName,
  clock,
  flightName,
  flightsCopy,
  routeName,
  shortDate,
} from './copy-flights.ts';

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

export type TicketKey = 'basic' | 'regular' | 'premium' | 'unsure';
export const TICKET_KEYS: readonly TicketKey[] = ['basic', 'regular', 'premium', 'unsure'];

export const tripsCopy = /* @__PURE__ */ deepFreeze({
  menu: 'My trips',
  title: 'My trips',
  next: 'Next trip',
  later: 'Later trips',
  past: 'Past trips',
  none: 'No trips yet. Search a flight and save it here.',
  signedOut: 'Sign in to save trips and get alerts when weather puts them at risk.',
  signIn: 'Sign in',
  loading: 'Loading your trips.',
  failed: 'We could not load your trips just now.',
  save: 'Save trip',
  saved: 'Saved',
  added: 'Added to your trips',
  remove: 'Remove trip',
  removed: 'Trip removed',
  open: 'Open trip',
  full: 'You have 20 trips. Remove one to save another.',
  saveFailed: 'We could not save this trip just now.',
  noTimes: 'We do not have the usual times of this flight on that day.',
  /** The rows of the next trip's card (LR-F18: a label and its value). */
  rows: {
    risk: 'Risk',
    cancel: 'Chance of a cancel',
    noForecast: 'No forecast yet',
  },
  /** The one tap (D19). */
  ticket: {
    question: 'What ticket did you buy?',
    hint: 'This changes our advice on switching. Not the chance.',
    basic: 'Basic economy',
    regular: 'Regular economy',
    premium: 'Premium or first',
    unsure: 'Not sure',
    skip: 'Skip',
    label: 'Ticket',
  },
  /** Which leg, when one flight number makes more than one stop that day (D19). */
  legPick: 'This flight number makes more than one stop. Which flight is yours?',
  needBy: {
    label: 'I need to be there by',
    none: 'Any time',
    clear: 'Clear',
  },
  backup: {
    title: 'Backup plans',
    hint: 'Other ways to get there. The safer ones come first, your airline first. Each is a rough chance of getting there with no cancel and no 45+ minute delay.',
    none: 'We found no other usual flights for this trip.',
    notRisky: 'This trip looks fine for now. We will show backup plans if the risk goes up.',
    noForecast: 'We can rank backup plans once there is a forecast for this day.',
    same: 'Same airline',
    other: 'Other airline',
    nearby: 'Nearby airport',
    hub: 'One stop',
    dayBefore: 'Day before',
    tooLate: 'Lands after the time you need to be there.',
    yours: 'Your flight',
    how: 'How to switch',
    /** D18's money words, shown with the options every time. */
    money: 'We don’t see prices or seats. Check with the airline before you switch.',
    rules: [
      'Many regular economy tickets on big US airlines can be changed with no change fee. You pay any difference in price.',
      'Basic economy often can’t be changed.',
      'Before big storms, airlines often post travel waivers that let you change for free.',
      'If the airline cancels and you choose not to fly, US rules give you your money back.',
    ],
    mustGo:
      'If you must get there, book a refundable backup on the best option and cancel the one you don’t use. This costs more.',
  },
  /** The advice by ticket type (D19), with the waiver state (W8). */
  advice: {
    regular:
      'Your ticket can usually be changed with no change fee. You pay any difference in price.',
    basic:
      'Basic economy often can’t be changed. Wait for a free-change waiver or for the airline to cancel. Then you get a refund or a free rebook.',
    unsure: 'Most regular tickets can be changed for no fee. Basic economy often can’t be.',
    watching: 'We will tell you if one appears.',
  },
  /** The alerts' first line, by what changed (D12). */
  alert: {
    rise: 'The risk for this trip went up.',
    fall: 'The risk for this trip went down.',
    safer: 'Another usual flight looks safer.',
    night: 'Evening check',
    /** Every push says the trip's day and time: "Leaves Tue, Jan 6 at 10:00 am." */
    leaves: 'Leaves',
    /** An evening check with no current forecast: never an old chance. */
    nightNone: 'We could not check the forecast for this trip. Look again in the morning.',
    /** An evening check whose forecast has no chance for this flight yet (the usual rate). */
    nightUsual: 'We have no forecast number for this flight. Its airport shows the usual rate.',
    /** A trip at risk with no safer usual flight left to catch (LR-F19.3). */
    noBackup: 'We see no safer usual flight you can still catch.',
    /**
     * A late alert whose carried safer flights have all left, when the sender found more
     * (TRAV-R5-B1). It speaks of this alert's flights only: some the sender found past them may
     * still be ahead (TRAV-R6-S1).
     */
    backupsGone: 'The safer flights in this alert have left. Open the trip to look for others.',
  },
  google: {
    title: 'Google',
    connect: 'Connect Google',
    connectHint:
      'Bring in flights from your Google calendar, and get alerts by email from your own Gmail.',
    connected: 'Connected',
    disconnect: 'Disconnect Google',
    disconnected: 'Google is disconnected.',
    failed: 'We could not connect Google just now.',
    denied: 'Google was not connected.',
    calendar: 'Find flights in my calendar',
    looking: 'Looking for flights.',
    found: 'Flights we found',
    foundHint: 'Check each one, then add it.',
    noneFound: 'We found no flights in your calendar for the next 60 days.',
    calendarFailed: 'We could not read your calendar just now.',
    add: 'Add',
    addAll: 'Add these',
    pick: 'Which flight is it?',
    notMatched: 'We could not match this to a usual flight.',
    /** The demo-only Gmail path (D19 GOOGLE RULE). */
    gmail: 'Find my flights in Gmail',
    gmailHint:
      'Reads airline confirmation emails from the last 6 months on this device. Nothing from your email is sent to us.',
    gmailFailed: 'We could not read your Gmail just now.',
    gmailNone: 'We found no airline emails with a flight in them.',
  },
  notify: {
    title: 'Flights',
    alerts: 'Trip alerts',
    alertsHint: 'When weather puts a saved trip at risk, with a safer flight when there is one.',
    /** This device's push state, in the Flights group: trip alerts need no saved school. */
    device: 'This device',
    deviceOn: 'On',
    deviceOff: 'Off',
    deviceBlocked: 'Blocked',
    offHint: 'Turn on notifications to get alerts here.',
    blockedHint:
      'Trip alerts will not come to this device. Allow notifications for this site in your browser settings.',
    cannotHint: 'Trip alerts will not come to this device.',
    turnOn: 'Turn on notifications',
    noSchools: 'School alerts start when you save a school.',
    thresholdHint:
      'We alert you when the chance of a cancel or a 45+ minute delay reaches this. The evening check tells you either way.',
    nightTime: 'Time, at the airport you leave from',
    threshold: 'Alert me at',
    night: 'Evening check the night before',
    email: 'Email me too',
    emailHint: 'Sent from your own Gmail to you.',
    emailOff: 'Connect Google on your trips page to get alerts by email.',
  },
  email: {
    brand: 'Snowlight',
    open: 'Open this trip',
    why: 'Why',
    backups: 'Backup plans',
    footer:
      'You get this email because you saved this trip and turned on email. Turn it off in your notification settings.',
  },
});

const LEVEL_WORDS = {
  low: flightsCopy.legend.low,
  delay: flightsCopy.legend.delay,
  cancel: flightsCopy.legend.cancel,
} as const;

/** A trip's status pill: "Low risk", "Some risk", "High risk". */
export function levelWord(level: 'low' | 'delay' | 'cancel'): string {
  return LEVEL_WORDS[level];
}

export function ticketName(key: TicketKey): string {
  return tripsCopy.ticket[key];
}

/** "Ticket: Basic economy". */
export function ticketLine(key: TicketKey): string {
  return `${tripsCopy.ticket.label}: ${tripsCopy.ticket[key]}`;
}

/** "WN 1234 · MCI to LAX". */
export function tripTitle(carrier: string, number: number, from: string, to: string): string {
  return `${flightName(carrier, number)} · ${routeName(from, to)}`;
}

/** "Mon, Jan 5 at 6:10 am". */
export function tripWhen(day: string, leaves: number): string {
  return `${shortDate(day)} at ${clock(leaves)}`;
}

/** A shown whole percent: "26%", "Under 1%". */
export function percentName(percent: number): string {
  return percent < 1 ? 'Under 1%' : `${String(percent)}%`;
}

/** "35% chance of a cancel", "Under 1% chance of a cancel". */
export function cancelWords(percent: number): string {
  return `${percent < 1 ? 'Under 1%' : `${String(percent)}%`} chance of a cancel`;
}

/** "20% chance of a 45+ minute delay". */
export function lateWords(percent: number): string {
  return `${percent < 1 ? 'Under 1%' : `${String(percent)}%`} chance of a 45+ minute delay`;
}

/** A backup's rough chance of getting there: "80% chance to get there on time". */
export function arriveWords(percent: number): string {
  return `${String(Math.max(0, Math.min(99, percent)))}% chance to get there on time`;
}

/** "WN 1500 at 9:05 am", or with its day: "WN 1500, Sun, Jan 4 at 9:05 am". */
export function backupName(carrier: string, number: number, leaves: number, day?: string): string {
  return day === undefined
    ? `${flightName(carrier, number)} at ${clock(leaves)}`
    : `${flightName(carrier, number)}, ${tripWhen(day, leaves)}`;
}

/** A one-stop backup: "WN 1500 and WN 2210 through DEN". */
export function viaName(first: string, second: string, hub: string): string {
  return `${first} and ${second} through ${hub}`;
}

/** A nearby airport, by straight line (D18): "MKC is about 12 miles away". */
export function nearbyWords(code: string, miles: number): string {
  return `${code} is about ${String(Math.max(1, Math.round(miles)))} miles away`;
}

/** The airline's link in the option rows: "Southwest’s travel alerts". */
export function switchLink(carrier: string): string {
  return `${airlineName(carrier)}’s travel alerts`;
}

/** W8 with a waiver: the advice leads with it. */
export function waiverAdvice(airline: string, basicIncluded: boolean): string {
  return basicIncluded
    ? `You can change for free. ${airline} posted a travel waiver that covers this trip, even for basic economy.`
    : `You can change for free. ${airline} posted a travel waiver that covers this trip.`;
}

/** W8 with an unclear waiver (LR-W1, LR-F10.4 words). */
export function waiverUnclearAdvice(airline: string): string {
  return `${airline} posted a travel waiver. We could not tell if it covers this trip. Check ${airline}’s page.`;
}

/** W8 not checked: D19's advice plus the link. */
export function waiverNotCheckedAdvice(airline: string): string {
  return `We could not check ${airline}’s page for a waiver just now.`;
}

/** The leg pick's chip: "MCI to DEN at 6:10 am". */
export function legName(from: string, to: string, leaves: number): string {
  return `${routeName(from, to)} at ${clock(leaves)}`;
}

/** "Connected as pat@example.com", with the day it was connected: "since Tue, Nov 24". */
export function connectedAs(email: string, day: string | null = null): string {
  return day === null ? `Connected as ${email}` : `Connected as ${email} since ${shortDate(day)}`;
}

/** A found calendar or email flight: "WN 1234 on Mon, Jan 5". */
export function foundName(carrier: string, number: number, day: string): string {
  return `${flightName(carrier, number)} on ${shortDate(day)}`;
}

/** The alert threshold choices: "30%". */
export function thresholdName(percent: number): string {
  return `${String(percent)}%`;
}

/** The quiet hours note in the Flights group: "Quiet hours, 10 pm to 5 am, hold these alerts." */
export function quietNote(from: string, to: string): string {
  return `Quiet hours, ${from} to ${to}, hold these alerts. FAA ground stops and delays still come through.`;
}

/** "Evening check at 8:00 pm". */
export function nightAt(minute: number): string {
  return clock(minute);
}

/** A settings time ("20:00") in the alerts' own style: "8:00 pm". */
export function settingTime(value: string): string {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  return match === null ? value : clock(Number(match[1]) * 60 + Number(match[2]));
}

// The Flights alerts (D12): one push, and its email, per change ----------------------------------

export type AlertKind = 'chance' | 'rise' | 'fall' | 'faa' | 'safer' | 'waiver' | 'night';

export interface AlertBackup {
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  readonly day: string;
  readonly leaves: number;
  /** The rough chance of getting there, in whole percent. */
  readonly chance: number;
  /** The second flight of a one-stop plan, and where it connects. */
  readonly via: { readonly carrier: string; readonly number: number; readonly hub: string } | null;
  /** Which kind of plan (backup.ts PlanKind), when the sender said. */
  readonly kind: 'same' | 'other' | 'nearby' | 'hub' | null;
  /** A nearby airport's straight-line miles from the trip's own end (D18). */
  readonly miles: number | null;
  /** When its first flight leaves (Unix seconds). */
  readonly departs: number;
}

/** What an alert says, as the sender sends it (modes/flights/alert.ts readAlert reads it). */
export interface AlertFacts {
  readonly alert: AlertKind;
  readonly trip: string;
  readonly carrier: string;
  readonly number: number;
  readonly from: string;
  readonly to: string;
  readonly day: string;
  readonly leaves: number;
  readonly cancel: number | null;
  readonly late: number | null;
  readonly level: 'low' | 'delay' | 'cancel' | null;
  readonly why: number | null;
  /** The airport whose forecast gives the reason. */
  readonly whyAt: string | null;
  /** When the sender checked, in Unix seconds. */
  readonly at: number | null;
  /** The same time on the departure airport's clock. */
  readonly checked: { readonly day: string; readonly minute: number } | null;
  /** `until`: the end the FAA gave, on that airport's clock, in minutes. */
  readonly faa: {
    readonly airport: string;
    readonly program: number;
    readonly until: number | null;
  } | null;
  /** `basic`: the waiver says plainly that basic economy is in it; `airport`: where it covers. */
  readonly waiver: {
    readonly state: 'waiver' | 'unclear';
    readonly basic: boolean;
    readonly airport: string | null;
  } | null;
  /** The sender's safer plans, best first: the top live one or two are named. */
  readonly backups: readonly AlertBackup[];
  /** The sender found safer plans past those carried (or may have: never read as none). */
  readonly more: boolean;
  readonly ticket: TicketKey;
  /** An evening check with no chance: the forecast was read and has none for this flight. */
  readonly noForecast: boolean;
}

const REASONS = [
  flightsCopy.why.snow,
  flightsCopy.why.ice,
  flightsCopy.why.thunder,
  flightsCopy.why.wind,
  flightsCopy.why.fog,
  flightsCopy.why.cold,
  flightsCopy.why.hubs,
  flightsCopy.why.before,
] as const;

/** The forecast's reason by its code, as a sentence: "Snow in the forecast at LAX." */
export function reasonSentence(code: number | null, at: string | null = null): string | null {
  const words = code === null ? undefined : REASONS[code];
  if (words === undefined) return null;
  return at === null ? `${words}.` : `${words} at ${at}.`;
}

/**
 * An FAA program at an airport, with the end the FAA gave it when it gave one, on that airport's
 * clock: named when it is not the airport the trip leaves from ("until 7:30 am, LAX time").
 */
export function faaSentence(
  airport: string,
  program: number,
  until: number | null = null,
  from: string = airport,
): string {
  const zone = from === airport ? '' : `, ${airport} time`;
  const end = until === null ? '' : ` until ${clock(until)}${zone}`;
  if (program === 4) return `${airport} is closed${end}.`;
  if (program === 1) return `The FAA has a ground delay at ${airport}${end}.`;
  return `The FAA has a ground stop at ${airport}${end}.`;
}

/** When the alert's facts were checked: "Checked Mon, Jan 5 at 8:20 pm, MCI time." */
export function checkedSentence(day: string, minute: number, airport: string): string {
  return `Checked ${tripWhen(day, minute)}, ${airport} time.`;
}

/** A waiver alert (W8): free to change, or for a basic ticket, only when the waiver says so. */
export function waiverAlert(
  airline: string,
  airport: string,
  state: 'waiver' | 'unclear',
  basicTicket: boolean,
  basicIncluded: boolean,
): string {
  const posted = `${airline} posted a travel waiver for ${airport}.`;
  if (state === 'unclear') return waiverUnclearAdvice(airline);
  if (basicTicket && !basicIncluded)
    return `${posted} We could not tell if it covers basic economy. Check ${airline}’s page.`;
  return `${posted} You can change this flight for free.`;
}

/** The alert's title: "WN 1234 · MCI to LAX". */
export function alertTitle(facts: AlertFacts): string {
  return tripTitle(facts.carrier, facts.number, facts.from, facts.to);
}

/**
 * The chance said in an alert: the cancel chance, and the delay when it is the bigger risk. An
 * evening check with no current forecast says so.
 */
function chanceSentence(facts: AlertFacts): string | null {
  if (facts.cancel === null) {
    if (facts.alert !== 'night') return null;
    return facts.noForecast ? tripsCopy.alert.nightUsual : tripsCopy.alert.nightNone;
  }
  const cancel = `${cancelWords(facts.cancel)}.`;
  if (facts.late !== null && facts.late > facts.cancel)
    return `${cancel} ${lateWords(facts.late)}.`;
  return cancel;
}

/**
 * A backup in a sentence: "Safer: WN 1500 at 9:05 am, 85% chance to get there on time." One the
 * day before says so: "Leave a day early: WN 1234, Mon, Jan 5 at 10:00 am, ...". A nearby
 * airport says how far, in a straight line (D18).
 */
export function backupSentence(backup: AlertBackup, day: string, from: string, to: string): string {
  const first = backupName(
    backup.carrier,
    backup.number,
    backup.leaves,
    backup.day === day ? undefined : backup.day,
  );
  const name =
    backup.via === null
      ? first
      : viaName(first, flightName(backup.via.carrier, backup.via.number), backup.via.hub);
  const elsewhere = backup.from !== from ? ` from ${backup.from}` : '';
  const landing = backup.to !== to ? ` to ${backup.to}` : '';
  const lead = backup.day < day ? 'Leave a day early' : 'Safer';
  const near = backup.to !== to ? backup.to : backup.from !== from ? backup.from : null;
  const away =
    near !== null && backup.miles !== null && backup.via === null
      ? ` ${nearbyWords(near, backup.miles)}.`
      : '';
  return `${lead}: ${name}${elsewhere}${landing}, ${arriveWords(backup.chance)}.${away}`;
}

/** When the trip leaves, as its own sentence: "Leaves Tue, Jan 6 at 10:00 am." */
function whenSentence(facts: AlertFacts): string {
  return `${tripsCopy.alert.leaves} ${tripWhen(facts.day, facts.leaves)}.`;
}

/** What the alert is about, first. */
function leadSentence(facts: AlertFacts): string {
  const airline = airlineName(facts.carrier);
  switch (facts.alert) {
    case 'faa':
      return facts.faa === null
        ? ''
        : faaSentence(facts.faa.airport, facts.faa.program, facts.faa.until, facts.from);
    case 'waiver':
      return facts.waiver === null
        ? ''
        : waiverAlert(
            airline,
            facts.waiver.airport ?? facts.from,
            facts.waiver.state,
            facts.ticket === 'basic',
            facts.waiver.basic,
          );
    case 'rise':
      return tripsCopy.alert.rise;
    case 'fall':
      return tripsCopy.alert.fall;
    case 'safer':
      return tripsCopy.alert.safer;
    case 'night':
      return `${tripsCopy.alert.night}: ${tripWhen(facts.day, facts.leaves)}.`;
    case 'chance':
      return whenSentence(facts);
  }
}

/**
 * The least time before a backup leaves for it to be named (LR-F19.3): time to change the
 * ticket, get to the airport and through security, 2 hours, and 3 from a nearby airport, a drive
 * away. One rule for the sender (flights_rules.py BACKUP_LEAD, NEARBY_LEAD), the page (backup.ts)
 * and a push or email shown late: shown at any time, it never offers a flight the sender would
 * not. Seconds.
 */
export const BACKUP_LEAD_S = 2 * 60 * 60;
export const NEARBY_LEAD_S = 3 * 60 * 60;

/** The alert's backups that can still be caught at `now` (Unix seconds; null: all of them). */
export function liveBackups(facts: AlertFacts, now: number | null): readonly AlertBackup[] {
  if (now === null) return facts.backups;
  return facts.backups.filter(
    (backup) =>
      backup.departs - now >= (backup.from === facts.from ? BACKUP_LEAD_S : NEARBY_LEAD_S),
  );
}

/** The safer plans an alert names: the top one or two (flights_rules.py ALERT_BACKUPS, D18). */
export const ALERT_NAMED = 2;

/**
 * The plan that made a safer alert (TRAV-R6-S2): of the one or two it names as sent, the one
 * with the best chance, as the sender sends a safer alert when that chance passes the best one
 * said before (flights_rules.py, the safer rule). Null for any other alert.
 */
function saferTrigger(sent: AlertFacts): AlertBackup | null {
  if (sent.alert !== 'safer') return null;
  let best: AlertBackup | null = null;
  for (const backup of sent.backups.slice(0, ALERT_NAMED))
    if (best === null || backup.chance > best.chance) best = backup;
  return best;
}

/**
 * Whether a safer alert shown at `now` still says something new: the plan that made it can still
 * be caught. One shown after that plan left would only name older plans, often ones the last
 * alert named already, so it reads as the chance (TRAV-R6-S2).
 */
function saferIsNew(sent: AlertFacts, now: number | null): boolean {
  const trigger = saferTrigger(sent);
  return trigger !== null && liveBackups({ ...sent, backups: [trigger] }, now).length > 0;
}

/**
 * The alert as it reads when shown at `now`: its backups that can still be caught, and a safer
 * alert whose new safer flight is gone reads as the chance it is (its "Another usual flight looks
 * safer." would no longer be so).
 */
function shownAt(facts: AlertFacts, now: number | null): AlertFacts {
  const backups = liveBackups(facts, now);
  const alert = facts.alert === 'safer' && !saferIsNew(facts, now) ? 'chance' : facts.alert;
  if (backups.length === facts.backups.length && alert === facts.alert) return facts;
  return { ...facts, alert, backups };
}

/**
 * Whether a push rings when shown at `now` (TRAV-R5-S1, TRAV-R6-S2): a safer alert whose new
 * safer flight has left says nothing new, so it replaces the last one without a sound.
 */
export function alertRings(sent: AlertFacts, now: number | null): boolean {
  return sent.alert !== 'safer' || saferIsNew(sent, now);
}

/**
 * The line said when the alert names no backup (LR-F19.3, TRAV-R5-B1), or null. "None left" only
 * when it is so: the sender found none, or every plan it found has left and it found no more.
 * When the ones it carried have left but it found more, it says so and points to the trip.
 */
function noBackupLine(sent: AlertFacts, shown: AlertFacts): string | null {
  if (shown.backups.length > 0) return null;
  if (sent.more) return sent.backups.length > 0 ? tripsCopy.alert.backupsGone : null;
  return noBackupSaid(shown) ? tripsCopy.alert.noBackup : null;
}

/**
 * An alert that names no backup says so (LR-F19.3) when the trip is at risk and the sender
 * looked for safer flights (every alert but a fall or a waiver).
 */
function noBackupSaid(facts: AlertFacts): boolean {
  return (
    facts.backups.length === 0 &&
    (facts.level === 'delay' || facts.level === 'cancel') &&
    facts.alert !== 'fall' &&
    facts.alert !== 'waiver'
  );
}

/** How old a push may be before it says when it was checked: the FAA read's limit, else an hour. */
export function staleAfter(kind: AlertKind): number {
  return kind === 'faa' ? 30 * 60 : 60 * 60;
}

function checkedOf(facts: AlertFacts): string | null {
  return facts.checked === null
    ? null
    : checkedSentence(facts.checked.day, facts.checked.minute, facts.from);
}

/** The advice line by ticket type, for an alert that names a backup. */
export function adviceOf(ticket: TicketKey): string {
  if (ticket === 'regular' || ticket === 'premium') return tripsCopy.advice.regular;
  if (ticket === 'basic') return tripsCopy.advice.basic;
  return tripsCopy.advice.unsure;
}

/**
 * The push's text: what changed, the chance, why, and the best backup with the money words
 * (D12, D18). `now` (Unix seconds): a push that reaches the phone late says when it was checked
 * first, so an old one never reads as current.
 */
export function alertBody(sent: AlertFacts, now: number | null = null): string {
  const facts = shownAt(sent, now);
  const parts: string[] = [];
  const checked = checkedOf(facts);
  if (
    now !== null &&
    facts.at !== null &&
    checked !== null &&
    now - facts.at > staleAfter(facts.alert)
  )
    parts.push(checked);
  // The trip's day and time in every push (a backup on its own day is named by its time alone):
  // the chance and evening leads are it.
  parts.push(leadSentence(facts));
  if (facts.alert !== 'chance' && facts.alert !== 'night') parts.push(whenSentence(facts));
  if (facts.alert !== 'waiver' && facts.alert !== 'faa') {
    const chance = chanceSentence(facts);
    if (chance !== null) parts.push(chance);
    const why = reasonSentence(facts.why, facts.whyAt);
    if (why !== null) parts.push(why);
  }
  const first = facts.backups[0];
  if (first !== undefined) {
    parts.push(backupSentence(first, facts.day, facts.from, facts.to));
    parts.push(tripsCopy.backup.money);
  } else {
    const line = noBackupLine(sent, facts);
    if (line !== null) parts.push(line);
  }
  return parts.filter((part) => part !== '').join(' ');
}

export interface AlertEmail {
  readonly subject: string;
  readonly text: string;
  readonly html: string;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * The alert's email (D12), in the site's look: the same rows as the trip's panel, light and dark,
 * with the top two backups, the money words and the link to the trip.
 */
export function alertEmail(sent: AlertFacts, link: string, now: number | null = null): AlertEmail {
  const facts = shownAt(sent, now);
  const title = alertTitle(facts);
  const lead = leadSentence(facts);
  const chance = chanceSentence(facts);
  const why = reasonSentence(facts.why, facts.whyAt);
  const checked = checkedOf(facts);
  const named = facts.backups
    .slice(0, ALERT_NAMED)
    .map((backup) => backupSentence(backup, facts.day, facts.from, facts.to));
  const none = noBackupLine(sent, facts);
  const backups = named.length === 0 && none !== null ? [none] : named;
  const advice = named.length > 0 ? [adviceOf(facts.ticket), tripsCopy.backup.money] : [];
  const subject = `${title}: ${facts.alert === 'faa' || facts.alert === 'waiver' ? lead : (chance ?? lead)}`;
  const rows: [string, string][] = [
    [flightName(facts.carrier, facts.number), tripWhen(facts.day, facts.leaves)],
  ];
  // The header already says when it leaves: a chance alert's own "when" line is not said twice.
  const lines = [
    ...(facts.alert === 'chance' ? [] : [lead]),
    ...(chance === null || facts.alert === 'faa' || facts.alert === 'waiver' ? [] : [chance]),
  ];
  const text = [
    tripsCopy.email.brand,
    '',
    title,
    rows[0]?.[1] ?? '',
    '',
    ...lines,
    ...(why === null ? [] : [why]),
    ...(backups.length === 0 ? [] : ['', `${tripsCopy.email.backups}:`, ...backups, ...advice]),
    ...(checked === null ? [] : ['', checked]),
    '',
    `${tripsCopy.email.open}: ${link}`,
    '',
    tripsCopy.email.footer,
  ].join('\n');
  // The gray lines take the dark theme's gray too.
  const p = (line: string, style = ''): string =>
    `<p${style.includes('#4a515a') ? ' class="sl-gray"' : ''} style="margin:0 0 8px;${style}">${escapeHtml(line)}</p>`;
  const html = [
    '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">',
    '<meta name="color-scheme" content="light dark"><style>',
    '@media (prefers-color-scheme: dark){.sl-page{background:#000000!important;color:#f5f5f5!important}.sl-card{background:#0a0a0a!important;border-color:#1f1f1f!important}.sl-gray{color:#a3a3a3!important}.sl-button{background:#f5f5f5!important;color:#000000!important}}',
    '</style></head>',
    '<body class="sl-page" style="margin:0;padding:24px 16px;background:#e9ecef;color:#0d1014;font-family:Geist,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.45">',
    '<div class="sl-card" style="max-width:480px;margin:0 auto;background:#ffffff;border:1px solid #e3e6ea;border-radius:16px;padding:20px">',
    `<p style="margin:0 0 16px;font-size:17px;font-weight:700;letter-spacing:-.01em">${escapeHtml(tripsCopy.email.brand)}</p>`,
    `<p class="sl-gray" style="margin:0 0 4px;font-size:13px;color:#4a515a">${escapeHtml(rows[0]?.[0] ?? '')} · ${escapeHtml(rows[0]?.[1] ?? '')}</p>`,
    `<h1 style="margin:0 0 12px;font-size:22px;line-height:1.2">${escapeHtml(routeName(facts.from, facts.to))}</h1>`,
    ...lines.map((line, i) => p(line, i === 0 ? 'font-weight:600' : '')),
    ...(why === null ? [] : [p(why, 'color:#4a515a')]),
    ...(backups.length === 0
      ? []
      : [
          `<p style="margin:16px 0 8px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.04em">${escapeHtml(tripsCopy.email.backups)}</p>`,
          ...backups.map((line) => p(line)),
          ...advice.map((line) => p(line, 'font-size:14px;color:#4a515a')),
        ]),
    ...(checked === null ? [] : [p(checked, 'margin-top:16px;font-size:13px;color:#4a515a')]),
    `<p style="margin:16px 0 0"><a href="${escapeHtml(link)}" class="sl-button" style="display:inline-block;padding:10px 16px;border-radius:999px;background:#0d1014;color:#ffffff;text-decoration:none;font-weight:600">${escapeHtml(tripsCopy.email.open)}</a></p>`,
    '</div>',
    `<p class="sl-gray" style="max-width:480px;margin:16px auto 0;font-size:12px;color:#4a515a">${escapeHtml(tripsCopy.email.footer)}</p>`,
    '</body></html>',
  ].join('');
  return { subject, text, html };
}

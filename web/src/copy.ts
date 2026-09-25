/**
 * Every customer-facing string in Snowlight lives in this file, and nowhere else.
 *
 * - `copy` holds the fixed strings, grouped by where they appear.
 * - `format` builds the strings that carry a live value: counts, times, delays,
 *   chances. Its phrasing lives here too, so no component composes words.
 * - `mapLocale` gives MapLibre's own control labels the same voice.
 *
 * House style: short, plain, confident, sentence case. No exclamation marks,
 * emoji or em dashes, no hedges or disclaimers, and never a word about where
 * the data comes from. The rules are in scripts/check-copy.mjs; src/copy.test.ts
 * runs them over every string here and over the formatters' output, and
 * `npm run lint:copy` keeps literal text out of components and index.html.
 *
 * The published files carry codes, not words (pipeline/snowlight/schemas/vocab.py).
 * STATUS_KEYS and REASON_KEYS turn a code into its key here: copy.status[STATUS_KEYS[code]].
 */

/** Recursively freezes an object graph so no string can be changed at runtime. */
function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

const description = 'School closings and delays for weather across the US, live on one map.';

export const copy = deepFreeze({
  appName: 'Snowlight',

  /** index.html: <title> and <meta name="description">. */
  meta: {
    description,
  },

  /** The web app manifest. */
  manifest: {
    name: 'Snowlight',
    shortName: 'Snowlight',
    description,
  },

  /** Share previews (Open Graph) and the share sheet. */
  share: {
    title: 'Snowlight',
    description,
    imageAlt: 'A dark map of the US with schools closed for weather glowing like city lights',
    copyLink: 'Copy link',
    copied: 'Link copied',
  },

  /** The About text, shown as one paragraph: what the site does, then how to use it. */
  about: {
    what: 'Snowlight maps schools that are closed, delayed, remote, or dismissing early for weather today.',
    how: 'Search a school, city, or ZIP to see its status and the chance of a weather closure today and tomorrow.',
  },

  search: {
    placeholder: 'Search a school, city, or ZIP',
    label: 'Search schools, cities, and ZIP codes',
    skip: 'Skip to search',
    clear: 'Clear search',
    results: 'Search results',
    noResults: 'No matches',
    /** The kind of each search result, keyed like the search index's kind codes. */
    kind: {
      school: 'School',
      district: 'District',
      city: 'City',
      zip: 'ZIP code',
    },
  },

  /** Status names: the legend, list rows and map labels. Keyed by STATUS_KEYS. */
  status: {
    closed: 'Closed',
    delayed: 'Delayed',
    remote: 'Remote',
    earlyDismissal: 'Early dismissal',
  },

  /** A school's status line in the detail panel, for today, tomorrow or a dated day. */
  statusLine: {
    closed: { today: 'Closed today', tomorrow: 'Closed tomorrow', on: 'Closed' },
    delayed: {
      today: 'Delayed start today',
      tomorrow: 'Delayed start tomorrow',
      on: 'Delayed start',
    },
    remote: {
      today: 'Remote learning today',
      tomorrow: 'Remote learning tomorrow',
      on: 'Remote learning',
    },
    earlyDismissal: {
      today: 'Early dismissal today',
      tomorrow: 'Early dismissal tomorrow',
      on: 'Early dismissal',
    },
  },

  /** Shown only for a school whose closings were checked live and have none. */
  open: {
    label: 'Open',
    today: 'Open today',
  },

  /** The weather named for a status or a forecast. Keyed by REASON_KEYS. */
  reason: {
    winterStorm: 'Winter storm',
    ice: 'Ice',
    extremeCold: 'Extreme cold',
    flooding: 'Flooding',
    hurricane: 'Hurricane',
    severeStorms: 'Severe storms',
    heat: 'Heat',
    powerOutage: 'Power outage',
  },

  /**
   * Weather alerts on the map, keyed like live/alerts.json. Each hazard covers
   * several alert types, so its name stays general: "Winter weather warning".
   */
  hazard: {
    winter: 'Winter weather',
    cold: 'Cold weather',
    flood: 'Flood',
    tropical: 'Tropical weather',
    heat: 'Heat',
    wind: 'Wind',
    severe: 'Severe weather',
  },
  alertLevel: {
    warning: 'Warning',
    watch: 'Watch',
    advisory: 'Advisory',
  },

  legend: {
    label: 'Legend',
    show: 'Show legend',
    hide: 'Hide legend',
    glow: 'Brighter means more schools',
  },

  empty: {
    noClosures: 'No weather closures today',
    notEnoughData: 'Not enough data yet',
    noThreat: 'No weather threat in the forecast',
  },

  actions: {
    replay: 'Replay a past storm',
    pin: 'Pin as my school',
    share: 'Share',
  },

  replay: {
    label: 'Replay',
    choose: 'Choose a storm',
    play: 'Play',
    pause: 'Pause',
    exit: 'Back to live',
    timeline: 'Replay timeline',
    speed: 'Playback speed',
    peak: 'Peak',
    schools: 'Schools affected',
    states: 'States',
  },

  detail: {
    label: 'School details',
    close: 'Close',
    back: 'Back',
    showOnMap: 'Show on map',
    posted: 'Posted',
    publicSchool: 'Public school',
    privateSchool: 'Private school',
    district: 'District',
  },

  /** The chance of a weather closure. "Not enough data yet" and "No weather threat" are in `empty`. */
  predictions: {
    title: 'Chance of a weather closure',
    noSchool: 'No school',
    delay: 'Delayed start',
    forecast: 'In the forecast',
  },

  pin: {
    mySchool: 'My school',
    pinned: 'Pinned as my school',
    unpin: 'Unpin',
  },

  days: {
    today: 'Today',
    tomorrow: 'Tomorrow',
  },

  /** The update time. "Live" itself is nav.live. */
  live: {
    updated: 'Updated',
    offline: 'Offline',
  },

  list: {
    label: 'Affected schools',
    mapView: 'Map view',
    sort: 'Sort by',
    all: 'All',
    columns: {
      school: 'School',
      status: 'Status',
      place: 'Place',
    },
  },

  nav: {
    live: 'Live',
    listView: 'List view',
    seasonStats: 'Season stats',
    trackRecord: 'Track record',
    about: 'About',
  },

  menu: {
    label: 'Menu',
    open: 'Open menu',
    close: 'Close menu',
  },

  /** Season stats: counts of school days, from stats/season.json. */
  season: {
    schoolsAffected: 'Schools affected',
    districtsAffected: 'Districts affected',
    closures: 'Closures',
    delays: 'Delayed starts',
    remote: 'Remote days',
    earlyDismissals: 'Early dismissals',
    busiestDay: 'Busiest day',
    byDay: 'By day',
    byState: 'By state',
  },

  /** Track record: how past chances compared with what schools did. */
  trackRecord: {
    chanceGiven: 'Chance given',
    happened: 'How often it happened',
    noSchool: 'No school',
    delay: 'Delayed start',
    daysScored: 'Days scored',
    /** Keyed by lead_days: 0 given that morning, 1 the day before, 2 two days before. */
    lead: {
      sameMorning: 'Same morning',
      dayBefore: 'Day before',
      twoDaysBefore: 'Two days before',
    },
  },

  /** MapLibre's controls and the map itself; applied through `mapLocale`. */
  map: {
    label: 'Map of weather school closings',
    unavailable: 'Map unavailable',
    zoomIn: 'Zoom in',
    zoomOut: 'Zoom out',
    resetNorth: 'Reset north',
    attribution: 'Map attribution',
    closePopup: 'Close',
  },
} as const);

export type Copy = typeof copy;
export type StatusKey = keyof Copy['status'];
export type ReasonKey = keyof Copy['reason'];
export type HazardKey = keyof Copy['hazard'];
export type AlertLevelKey = keyof Copy['alertLevel'];
export type SearchKind = keyof Copy['search']['kind'];

/** Status keys in code order, as the published files number them: 0 closed … 3 early dismissal. */
export const STATUS_KEYS: readonly StatusKey[] = /* @__PURE__ */ Object.freeze([
  'closed',
  'delayed',
  'remote',
  'earlyDismissal',
] as const);

/** Reason keys in code order, as the published files number them: 0 winter storm … 7 power outage. */
export const REASON_KEYS: readonly ReasonKey[] = /* @__PURE__ */ Object.freeze([
  'winterStorm',
  'ice',
  'extremeCold',
  'flooding',
  'hurricane',
  'severeStorms',
  'heat',
  'powerOutage',
] as const);

/**
 * Labels for MapLibre's controls, keyed by MapLibre's string ids. Pass it as the
 * map's `locale` option so no English default reaches the page.
 */
export const mapLocale: Readonly<Record<string, string>> = /* @__PURE__ */ deepFreeze({
  'Map.Title': copy.map.label,
  'NavigationControl.ZoomIn': copy.map.zoomIn,
  'NavigationControl.ZoomOut': copy.map.zoomOut,
  'NavigationControl.ResetBearing': copy.map.resetNorth,
  'AttributionControl.ToggleAttribution': copy.map.attribution,
  'Popup.Close': copy.map.closePopup,
});

// Formatters ------------------------------------------------------------------------

const LOCALE = 'en-US';
/** Between a time and AM or PM, so "6:42 AM" never breaks across lines. */
const NBSP = '\u00a0';
/** Between two parts of one line: "Live · 6:42 AM". */
const DOT = ' · ';
const MS_PER_DAY = 86_400_000;
const LOCAL_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const SCHOOL_YEAR = /^(\d{4})-(\d{4})$/;

let numberFormat: Intl.NumberFormat | undefined;
let speedFormat: Intl.NumberFormat | undefined;
const dateTimeFormats = new Map<string, Intl.DateTimeFormat>();

type DateStyle = 'clock' | 'day' | 'monthDay' | 'dayYear' | 'ymd';

const DATE_STYLES: Readonly<Record<DateStyle, Intl.DateTimeFormatOptions>> = {
  clock: { hour: 'numeric', minute: '2-digit', hourCycle: 'h23' },
  day: { weekday: 'short', month: 'short', day: 'numeric' },
  monthDay: { month: 'short', day: 'numeric' },
  dayYear: { month: 'short', day: 'numeric', year: 'numeric' },
  ymd: { year: 'numeric', month: '2-digit', day: '2-digit' },
};

/** One cached Intl formatter per style and time zone; an unknown zone throws RangeError. */
function dateTimeFormat(style: DateStyle, timeZone: string): Intl.DateTimeFormat {
  const key = `${style} ${timeZone}`;
  let formatter = dateTimeFormats.get(key);
  if (formatter === undefined) {
    formatter = new Intl.DateTimeFormat(LOCALE, { ...DATE_STYLES[style], timeZone });
    dateTimeFormats.set(key, formatter);
  }
  return formatter;
}

function part(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string {
  const found = parts.find((entry) => entry.type === type);
  if (found === undefined) throw new RangeError(`copy: no ${type} in a formatted date`);
  return found.value;
}

function checkInstant(instant: Date): Date {
  if (Number.isNaN(instant.getTime())) throw new RangeError('copy: invalid date');
  return instant;
}

/** A key of one of the copy tables, checked at runtime too: a bad key never prints "undefined". */
function checkKey<T extends object>(table: T, key: PropertyKey, what: string): keyof T {
  if (typeof key !== 'string' || !Object.hasOwn(table, key)) {
    throw new RangeError(`copy: no ${what} named ${String(key)}`);
  }
  return key as keyof T;
}

function checkCount(n: number, what = 'count'): number {
  if (!Number.isSafeInteger(n) || n < 0) {
    throw new RangeError(`copy: ${what} must be a whole number of 0 or more, not ${String(n)}`);
  }
  return n;
}

/** Parses a LocalDate (YYYY-MM-DD) to midnight UTC of that calendar day. */
function parseLocalDate(day: string): Date {
  const match = LOCAL_DATE.exec(day);
  if (match !== null) {
    const year = Number(match[1]);
    const month = Number(match[2]) - 1;
    const date = Number(match[3]);
    const parsed = new Date(Date.UTC(year, month, date));
    if (
      parsed.getUTCFullYear() === year &&
      parsed.getUTCMonth() === month &&
      parsed.getUTCDate() === date
    ) {
      return parsed;
    }
  }
  throw new RangeError(`copy: "${day}" is not a calendar date (YYYY-MM-DD)`);
}

/** The calendar day of an instant in a time zone, as YYYY-MM-DD. */
function localDay(instant: Date, timeZone: string): string {
  const parts = dateTimeFormat('ymd', timeZone).formatToParts(checkInstant(instant));
  return `${part(parts, 'year')}-${part(parts, 'month')}-${part(parts, 'day')}`;
}

/** "6:42 AM" from an hour (0-23) and minute. */
function clockText(hour24: number, minute: number): string {
  const hour = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${String(hour)}:${String(minute).padStart(2, '0')}${NBSP}${hour24 < 12 ? 'AM' : 'PM'}`;
}

function plural(n: number, one: string, other: string): string {
  return `${number(n)} ${n === 1 ? one : other}`;
}

/** A shift length as a noun: "1 hour", "90 minutes", "2½ hours". */
function durationNoun(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  if (minutes < 60) return plural(minutes, 'minute', 'minutes');
  if (minutes % 60 === 0) return plural(hours, 'hour', 'hours');
  if (minutes > 120 && minutes % 60 === 30) return `${String(hours)}½ hours`;
  return plural(minutes, 'minute', 'minutes');
}

/** A shift length as an adjective: "1-hour", "90-minute", "2½-hour". */
function durationAdjective(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  if (minutes >= 60 && minutes % 60 === 0) return `${String(hours)}-hour`;
  if (minutes > 120 && minutes % 60 === 30) return `${String(hours)}½-hour`;
  return `${number(minutes)}-minute`;
}

function checkShift(minutes: number): number {
  if (!Number.isInteger(minutes) || minutes < 1 || minutes > 720) {
    throw new RangeError(`copy: a shift is 1 to 720 minutes, not ${String(minutes)}`);
  }
  return minutes;
}

/** A whole number with thousands separators: "1,284". */
function number(n: number): string {
  numberFormat ??= new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
  return numberFormat.format(checkCount(n));
}

/** A status and how many schools have it: "Closed 1,284". */
function count(status: StatusKey, n: number): string {
  return `${copy.status[checkKey(copy.status, status, 'status')]} ${number(n)}`;
}

/**
 * Every status with at least one school, in code order: "Closed 1,284 · Delayed 311".
 * Null when no status has a school.
 */
function summary(counts: Readonly<Partial<Record<StatusKey, number>>>): string | null {
  const parts: string[] = [];
  for (const status of STATUS_KEYS) {
    const n = counts[status];
    if (n !== undefined && checkCount(n) > 0) parts.push(count(status, n));
  }
  return parts.length > 0 ? parts.join(DOT) : null;
}

/** "1 school", "1,284 schools". */
function schools(n: number): string {
  return plural(n, 'school', 'schools');
}

/** For the search results announcement: "No matches", "1 result", "12 results". */
function results(n: number): string {
  return checkCount(n) === 0 ? copy.search.noResults : plural(n, 'result', 'results');
}

/** A local wall-clock time from minutes after midnight (630 is "10:30 AM"). */
function clock(minuteOfDay: number): string {
  if (!Number.isInteger(minuteOfDay) || minuteOfDay < 0 || minuteOfDay >= 1440) {
    throw new RangeError(`copy: a minute of the day is 0 to 1439, not ${String(minuteOfDay)}`);
  }
  return clockText(Math.floor(minuteOfDay / 60), minuteOfDay % 60);
}

/** An instant as a time of day in an IANA time zone: "6:42 AM". */
function time(instant: Date, timeZone: string): string {
  const parts = dateTimeFormat('clock', timeZone).formatToParts(checkInstant(instant));
  // Some engines write midnight as 24 even in the h23 cycle.
  return clockText(Number(part(parts, 'hour')) % 24, Number(part(parts, 'minute')));
}

/** A calendar day (YYYY-MM-DD): "Mon, Jan 12". */
function day(localDate: string): string {
  return dateTimeFormat('day', 'UTC').format(parseLocalDate(localDate));
}

/** A calendar day without its weekday (YYYY-MM-DD): "Jan 12". */
function monthDay(localDate: string): string {
  return dateTimeFormat('monthDay', 'UTC').format(parseLocalDate(localDate));
}

/** A calendar day with its year (YYYY-MM-DD): "Jan 12, 2026". */
function dayWithYear(localDate: string): string {
  return dateTimeFormat('dayYear', 'UTC').format(parseLocalDate(localDate));
}

/** The time alone when `instant` falls on the same local day as `now`, else the day and time. */
function stamp(instant: Date, timeZone: string, now: Date): string {
  const when = time(instant, timeZone);
  const localDate = localDay(instant, timeZone);
  return localDate === localDay(now, timeZone) ? when : `${day(localDate)}, ${when}`;
}

/** The live update time in the viewer's time zone: "Live · 6:42 AM". */
function liveAt(instant: Date, timeZone: string): string {
  return `${copy.nav.live}${DOT}${time(instant, timeZone)}`;
}

/** An older update: "Updated 6:42 AM", or "Updated Mon, Jan 12, 6:42 AM" on another day. */
function updatedAt(instant: Date, timeZone: string, now: Date): string {
  return `${copy.live.updated} ${stamp(instant, timeZone, now)}`;
}

/** No connection: "Offline · Updated 6:42 AM". */
function offline(instant: Date, timeZone: string, now: Date): string {
  return `${copy.live.offline}${DOT}${updatedAt(instant, timeZone, now)}`;
}

/** When a school posted its status: "Posted 5:12 AM", or "Posted Sun, Jan 11, 8:30 PM". */
function posted(instant: Date, timeZone: string, now: Date): string {
  return `${copy.detail.posted} ${stamp(instant, timeZone, now)}`;
}

/**
 * A school's status line for its local `localDate`, measured against today in the
 * school's time zone: "Closed today", "Delayed start tomorrow", "Closed Mon, Jan 12".
 */
function statusOn(status: StatusKey, localDate: string, now: Date, timeZone: string): string {
  const offset = Math.round(
    (parseLocalDate(localDate).getTime() - parseLocalDate(localDay(now, timeZone)).getTime()) /
      MS_PER_DAY,
  );
  const line = copy.statusLine[checkKey(copy.statusLine, status, 'status')];
  if (offset === 0) return line.today;
  if (offset === 1) return line.tomorrow;
  return `${line.on} ${day(localDate)}`;
}

/**
 * The detail of a delayed start, from shift_minutes and clock_minute:
 * "2-hour delay", "Starts at 10:00 AM", "2-hour delay · Starts at 10:00 AM".
 * Null when neither is known.
 */
function delay(shiftMinutes: number | null, clockMinute: number | null): string | null {
  const parts: string[] = [];
  if (shiftMinutes !== null) parts.push(`${durationAdjective(checkShift(shiftMinutes))} delay`);
  if (clockMinute !== null) parts.push(`Starts at ${clock(clockMinute)}`);
  return parts.length > 0 ? parts.join(DOT) : null;
}

/**
 * The detail of an early dismissal, from shift_minutes and clock_minute:
 * "2 hours early", "Dismissal at 12:30 PM", "Dismissal at 12:30 PM · 2 hours early".
 * Null when neither is known.
 */
function dismissal(shiftMinutes: number | null, clockMinute: number | null): string | null {
  const parts: string[] = [];
  if (clockMinute !== null) parts.push(`Dismissal at ${clock(clockMinute)}`);
  if (shiftMinutes !== null) parts.push(`${durationNoun(checkShift(shiftMinutes))} early`);
  return parts.length > 0 ? parts.join(DOT) : null;
}

/** A probability from 0 to 1 as a whole percentage: "34%", "<1%", ">99%". */
function chance(probability: number): string {
  if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
    throw new RangeError(`copy: a probability is 0 to 1, not ${String(probability)}`);
  }
  const percent = Math.round(probability * 100);
  if (percent < 1) return '<1%';
  if (percent > 99) return '>99%';
  return `${String(percent)}%`;
}

/** A track record bin of whole percentages: "40–50%". */
function percentRange(low: number, high: number): string {
  if (!Number.isInteger(low) || !Number.isInteger(high) || low < 0 || high > 100 || low >= high) {
    throw new RangeError(`copy: ${String(low)}–${String(high)} is not a percentage range`);
  }
  return `${String(low)}–${String(high)}%`;
}

/** "9 of 20". */
function outOf(some: number, all: number): string {
  if (checkCount(some) > checkCount(all)) {
    throw new RangeError(`copy: ${String(some)} is more than ${String(all)}`);
  }
  return `${number(some)} of ${number(all)}`;
}

/** How far ahead a chance was given, from lead_days: "Same morning", "Day before". */
function lead(leadDays: number): string {
  const labels = copy.trackRecord.lead;
  const label = [labels.sameMorning, labels.dayBefore, labels.twoDaysBefore][leadDays];
  if (label === undefined) {
    throw new RangeError(`copy: no label for ${String(leadDays)} days ahead`);
  }
  return label;
}

/** A school year (YYYY-YYYY, July to June): "2025–26". */
function season(schoolYear: string): string {
  const match = SCHOOL_YEAR.exec(schoolYear);
  const first = Number(match?.[1] ?? NaN);
  const second = Number(match?.[2] ?? NaN);
  if (second !== first + 1) {
    throw new RangeError(`copy: "${schoolYear}" is not a school year (YYYY-YYYY)`);
  }
  return `${String(first)}–${String(second % 100).padStart(2, '0')}`;
}

/** The last day a count covers: "Through Jan 12". */
function through(localDate: string): string {
  return `Through ${monthDay(localDate)}`;
}

/** The days a track record covers: "Jan 5 to Mar 2, 2026", "Dec 1, 2025 to Mar 2, 2026". */
function span(first: string, last: string): string {
  const start = parseLocalDate(first);
  const end = parseLocalDate(last);
  if (start > end) throw new RangeError(`copy: ${first} is after ${last}`);
  if (first === last) return dayWithYear(last);
  const sameYear = start.getUTCFullYear() === end.getUTCFullYear();
  return `${sameYear ? monthDay(first) : dayWithYear(first)} to ${dayWithYear(last)}`;
}

/** A replay frame's moment in a time zone: "Mon, Jan 12 · 6:00 AM". */
function replayMoment(instant: Date, timeZone: string): string {
  return `${day(localDay(instant, timeZone))}${DOT}${time(instant, timeZone)}`;
}

/** Replay speed, to two decimals at most: "4×", "0.5×", "1,000×". Never "0×". */
function speed(multiple: number): string {
  if (!Number.isFinite(multiple) || multiple < 0.005) {
    throw new RangeError(`copy: a speed is at least 0.01, not ${String(multiple)}`);
  }
  speedFormat ??= new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 });
  return `${speedFormat.format(multiple)}×`;
}

/** A weather alert: "Winter weather warning". */
function alertName(hazard: HazardKey, level: AlertLevelKey): string {
  const name = copy.hazard[checkKey(copy.hazard, hazard, 'hazard')];
  const kind = copy.alertLevel[checkKey(copy.alertLevel, level, 'alert level')];
  return `${name} ${kind.toLocaleLowerCase(LOCALE)}`;
}

export const format = /* @__PURE__ */ deepFreeze({
  number,
  count,
  summary,
  schools,
  results,
  clock,
  time,
  day,
  dayWithYear,
  liveAt,
  updatedAt,
  offline,
  posted,
  statusOn,
  delay,
  dismissal,
  chance,
  percentRange,
  outOf,
  lead,
  season,
  through,
  span,
  replayMoment,
  speed,
  alert: alertName,
});

export type Format = typeof format;

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

  /**
   * The menu's About, in two lines: what the site is, then how to read its
   * lights. It never names the site (the wordmark above it does) and never
   * says how to search (the field above it does).
   */
  about: {
    what: 'Live school closings and delays for weather.',
    glow: 'The brighter the glow, the more schools.',
  },

  search: {
    placeholder: 'Search a school, city, or ZIP',
    label: 'Search schools, cities, and ZIP codes',
    skip: 'Skip to search',
    clear: 'Clear search',
    results: 'Search results',
    noResults: 'No matches',
    /** The heading over each kind of search result, keyed like the search index's kind codes. */
    sections: {
      city: 'Places',
      zip: 'ZIP codes',
      district: 'Districts',
      school: 'Schools',
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
    charterSchool: 'Charter school',
    virtualSchool: 'Virtual school',
    district: 'District',
    grades: 'Grades',
    students: 'Students',
    address: 'Address',
    phone: 'Phone',
    /** The status heading over today's and tomorrow's lines. */
    status: 'Status',
    nearby: 'Nearby schools',
    /** The phone sheet's grip, for a screen reader: it takes the sheet up, or back down. */
    more: 'Show more',
    less: 'Show less',
  },

  /** The chance of a weather closure. "No weather threat" is in `empty`. */
  predictions: {
    title: 'Chance of a weather closure',
    noSchool: 'No school',
    delay: 'Delayed start',
    forecast: 'In the forecast',
  },

  /**
   * The school panel's chance section: the chance of no school as its headline,
   * the evening's early signals, the night hour by hour, and how the chance adds
   * up. Its sentences, which carry live values, are the `format` functions below
   * (format.reason and the rest); these are its fixed words.
   */
  chance: {
    /** Before the weekday: "Chance of no school Tuesday". */
    noSchool: 'Chance of no school',
    /** Before the chance: "How we got 64%". */
    howWeGot: 'How we got',
    key: 'Each reason adds or takes away points.',
    start: 'Where we start:',
    /** The chart's titles. */
    snowTitle: 'Snow on the ground, hour by hour',
    coldTonight: 'How cold it will feel tonight',
    coldTitle: 'How cold it will feel, hour by hour',
    /** Under the chart's first hour, when that hour is this one. */
    now: 'Now',
    /** The chart's two moments: "Usually announces 5:30 AM", "Buses 7 AM". */
    usuallyAnnounces: 'Usually announces',
    buses: 'Buses',
    /** Words beside the lit bars: "Heaviest snow 2 to 5 AM". */
    heaviest: 'Heaviest snow',
    /** A day in a district's record, by what it did. */
    open: 'Open',
    closed: 'Closed',
    delayed: 'Delayed',
    remote: 'Remote',
    earlyDismissal: 'Early dismissal',
    /** For a screen reader: the record under a reason, and which way the chance moved. */
    record: 'The district’s record',
    up: 'Up',
    down: 'Down',
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
    /** The first group: which of today's lights the map shows, all four statuses or one. */
    today: 'Today',
    all: 'All',
    /** The second: which schools the map shows. */
    kinds: 'Schools',
    public: 'Public',
    private: 'Private',
    /** What the map holds, on the About page: every school in the directory, and their districts. */
    onMap: 'On the map',
    schools: 'Schools',
    districts: 'Districts',
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
  },

  /** Track record: how past chances compared with what schools did. */
  trackRecord: {
    chanceGiven: 'Chance given',
    /** Over the table: each row is a chance of no school given, each cell how many of those days had none. */
    caption: 'Days with no school',
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
    /** The button that takes the map to where the phone is. */
    locate: 'Show my area',
  },
} as const);

export type Copy = typeof copy;
export type StatusKey = keyof Copy['status'];
export type ReasonKey = keyof Copy['reason'];
export type HazardKey = keyof Copy['hazard'];
export type AlertLevelKey = keyof Copy['alertLevel'];
export type SearchKind = keyof Copy['search']['sections'];

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

type DateStyle = 'clock' | 'day' | 'monthDay' | 'dayYear' | 'ymd' | 'weekday';

const DATE_STYLES: Readonly<Record<DateStyle, Intl.DateTimeFormatOptions>> = {
  clock: { hour: 'numeric', minute: '2-digit', hourCycle: 'h23' },
  day: { weekday: 'short', month: 'short', day: 'numeric' },
  monthDay: { month: 'short', day: 'numeric' },
  dayYear: { month: 'short', day: 'numeric', year: 'numeric' },
  ymd: { year: 'numeric', month: '2-digit', day: '2-digit' },
  weekday: { weekday: 'long' },
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

/** How a grade code reads (NCES codes: PK, TK, KG, 01 to 13). */
const GRADE_NAMES: Readonly<Record<string, string>> = {
  PK: 'PK',
  TK: 'TK',
  KG: 'K',
};

function gradeName(code: string): string {
  const named = GRADE_NAMES[code];
  if (named !== undefined) return named;
  const grade = /^(?:0[1-9]|1[0-3])$/.exec(code) === null ? NaN : Number(code);
  if (Number.isNaN(grade)) throw new RangeError(`copy: "${code}" is not a grade`);
  return String(grade);
}

/** A school's grades from its lowest and highest, as NCES codes: "PK–12", "K–5", "9–12", "K". */
function grades(low: string, high: string): string {
  const first = gradeName(low);
  const last = gradeName(high);
  return first === last ? first : `${first}–${last}`;
}

/** A 10-digit US phone number: "(816) 936-1230". */
function phone(digits: string): string {
  if (!/^\d{10}$/.test(digits)) throw new RangeError(`copy: "${digits}" is not a phone number`);
  return `(${digits.slice(0, 3)})${NBSP}${digits.slice(3, 6)}-${digits.slice(6)}`;
}

const METRES_PER_MILE = 1609.344;

/** A distance in miles, from metres: "0.4 mi" under ten miles, "12 mi" beyond; never under "0.1 mi". */
function miles(metres: number): string {
  if (!Number.isFinite(metres) || metres < 0) {
    throw new RangeError(`copy: a distance is 0 metres or more, not ${String(metres)}`);
  }
  const tenths = Math.max(1, Math.round((metres / METRES_PER_MILE) * 10));
  if (tenths < 100) return `${(tenths / 10).toFixed(1)}${NBSP}mi`;
  return `${number(Math.round(metres / METRES_PER_MILE))}${NBSP}mi`;
}

/** A weather alert: "Winter weather warning". */
function alertName(hazard: HazardKey, level: AlertLevelKey): string {
  const name = copy.hazard[checkKey(copy.hazard, hazard, 'hazard')];
  const kind = copy.alertLevel[checkKey(copy.alertLevel, level, 'alert level')];
  return `${name} ${kind.toLocaleLowerCase(LOCALE)}`;
}

// The chance section -------------------------------------------------------------------
//
// The predictions file sends kinds and numbers, never words (pipeline/snowlight/schemas/
// predictions.py): each sentence here is written from them. A time is the viewer's
// wall clock, as every time on the site is.

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
/** A true minus, so a take-away lines up with the pluses: "−3". */
const MINUS = '\u2212';

/** The weather alerts a district's base chance is counted over, as a plural noun. */
const ALERT_PLURALS = {
  winter_storm_warning: 'winter storm warnings',
  winter_weather_advisory: 'winter weather advisories',
  ice_storm_warning: 'ice storm warnings',
  blizzard_warning: 'blizzard warnings',
  extreme_cold_warning: 'extreme cold warnings',
} as const;

export type AlertKind = keyof typeof ALERT_PLURALS;

/** A sentence in two parts: the bold words that lead it, then the rest, which starts with a space. */
export interface Said {
  readonly lead: string;
  readonly rest: string;
}

/** A status a district posted, as the chance section words it. */
export type PostedKey = StatusKey;

/** The base of the sum: where the chance starts for a district. */
export type BaseInput =
  | { readonly kind: 'alert'; readonly points: number; readonly alert: AlertKind }
  | { readonly kind: 'day_after'; readonly points: number }
  | { readonly kind: 'similar_days'; readonly points: number };

/** The district's record in storms like this, counted, for the sentence that cites it. */
export interface RecordCount {
  /** Days with no school (closed or remote). */
  readonly closed: number;
  /** Days counted. */
  readonly days: number;
  /** The least snow of a storm counted. */
  readonly inches: number;
}

/** One reason and what it needs to be said. Times are instants; the viewer's zone words them. */
export type ReasonInput =
  | {
      readonly kind: 'snow_total';
      readonly points: number;
      readonly low: number;
      readonly high: number;
      readonly overnight: boolean;
      /** The record the sentence cites, or null to leave that sentence out. */
      readonly record: RecordCount | null;
    }
  | { readonly kind: 'record'; readonly points: number; readonly record: RecordCount }
  | {
      readonly kind: 'neighbors';
      readonly points: number;
      /** The districts' short names, or null where they cannot be read: then only how many. */
      readonly names: readonly string[] | null;
      readonly count: number;
      readonly status: PostedKey;
    }
  | {
      readonly kind: 'timing';
      readonly points: number;
      readonly start: Date;
      readonly end: Date;
      readonly buses: Date | null;
    }
  | { readonly kind: 'wind_chill'; readonly points: number; readonly feelsLike: number }
  | {
      readonly kind: 'cold';
      readonly points: number;
      readonly feelsLike: number;
      /** The day it is for (YYYY-MM-DD). */
      readonly day: string;
    }
  | {
      readonly kind: 'snow_stops';
      readonly points: number;
      readonly at: Date;
      readonly buses: Date | null;
      /** The day the chance is for (YYYY-MM-DD). */
      readonly day: string;
    }
  | { readonly kind: 'sun'; readonly points: number }
  | { readonly kind: 'icy_roads'; readonly points: number; readonly inches: number }
  | { readonly kind: 'ice'; readonly points: number; readonly inches: number };

/** Where a chance moved from: the run before, and when it was made. */
export interface MovedInput {
  readonly previous: number;
  readonly current: number;
  readonly at: Date;
  readonly now: Date;
  readonly timeZone: string;
}

/**
 * The hour of the day (0 to 23) an instant falls in, in a time zone. Not words:
 * the chance section's chart uses it to choose which hours to name.
 */
export function localHour(instant: Date, timeZone: string): number {
  const parts = dateTimeFormat('clock', timeZone).formatToParts(checkInstant(instant));
  return Number(part(parts, 'hour')) % 24;
}

/** A calendar day (YYYY-MM-DD) as its weekday: "Tuesday". */
function weekday(localDate: string): string {
  return dateTimeFormat('weekday', 'UTC').format(parseLocalDate(localDate));
}

/** "Chance of no school Tuesday", for a calendar day. */
function chanceOn(localDate: string): string {
  return `${copy.chance.noSchool} ${weekday(localDate)}`;
}

/** The headline number without its sign: "64", or "<1" and ">99" at the ends, as chance() says. */
function chanceNumber(probability: number): string {
  return chance(probability).slice(0, -1);
}

/** "How we got 64%". */
function howWeGot(probability: number): string {
  return `${copy.chance.howWeGot} ${chance(probability)}`;
}

/** Whole percentage points with their sign: "+16", "−3". */
function points(n: number): string {
  if (!Number.isInteger(n) || n === 0) {
    throw new RangeError(`copy: points are a whole number other than 0, not ${String(n)}`);
  }
  return n > 0 ? `+${String(n)}` : `${MINUS}${String(-n)}`;
}

/** A time of day, to the minute only where it is not on the hour: "5 PM", "5:30 AM". */
function shortTime(instant: Date, timeZone: string): string {
  const parts = dateTimeFormat('clock', timeZone).formatToParts(checkInstant(instant));
  const hour24 = Number(part(parts, 'hour')) % 24;
  const minute = Number(part(parts, 'minute'));
  if (minute !== 0) return clockText(hour24, minute);
  const hour = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${String(hour)}${NBSP}${hour24 < 12 ? 'AM' : 'PM'}`;
}

/** Hours from one time to another: "2 to 5 AM", "11 PM to 2 AM", "2:30 to 5 AM". */
function hourSpan(start: Date, end: Date, timeZone: string): string {
  const from = shortTime(start, timeZone);
  const to = shortTime(end, timeZone);
  const half = (text: string): string => text.slice(-2);
  const bare = (text: string): string => text.slice(0, -3);
  return half(from) === half(to) ? `${bare(from)} to ${to}` : `${from} to ${to}`;
}

/** The local calendar day of an instant (YYYY-MM-DD). */
function dayOf(instant: Date, timeZone: string): string {
  return localDay(instant, timeZone);
}

/**
 * Which way the chance moved since the run before, and from what:
 * "Up from 41% at 5 PM", "Down from 30% last night", "Up from 12% yesterday",
 * "Down from 50% on Sunday", "Same as at 5 PM". Null for a run more than six
 * days old, which says nothing about tonight.
 */
function moved(input: MovedInput): string | null {
  const { previous, current, at, now, timeZone } = input;
  const days = Math.round(
    (parseLocalDate(dayOf(now, timeZone)).getTime() -
      parseLocalDate(dayOf(at, timeZone)).getTime()) /
      MS_PER_DAY,
  );
  if (days < 0 || days > 6 || at.getTime() > now.getTime()) return null;
  const hour = localHour(at, timeZone);
  const when =
    days === 0
      ? `at ${shortTime(at, timeZone)}`
      : days === 1
        ? hour >= 17
          ? 'last night'
          : 'yesterday'
        : `on ${weekday(dayOf(at, timeZone))}`;
  const before = Math.round(previous * 100);
  const after = Math.round(current * 100);
  if (before === after) return `Same as ${when}`;
  return `${before < after ? 'Up' : 'Down'} from ${chance(previous)} ${when}`;
}

/**
 * How long until a moment, for the district's usual announcement: "in 8h 25m",
 * "in 45m", "in 8h"; with its weekday when it is half a day or more away:
 * "Wednesday, in 23h 10m". Null once the moment has come.
 */
function countdown(at: Date, now: Date, timeZone: string): string | null {
  // Whole minutes still to go, rounded up: 30 seconds before is "in 1m".
  const minutes = Math.ceil((checkInstant(at).getTime() - checkInstant(now).getTime()) / MINUTE_MS);
  if (minutes <= 0) return null;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const span =
    hours === 0
      ? `${String(rest)}m`
      : rest === 0
        ? `${String(hours)}h`
        : `${String(hours)}h ${String(rest)}m`;
  return minutes >= 12 * 60 ? `${weekday(dayOf(at, timeZone))}, in ${span}` : `in ${span}`;
}

/** A moment on the section's timeline: its time within the last day, else its day: "8:41 PM", "Mon, Jan 12". */
function momentTime(instant: Date, now: Date, timeZone: string): string {
  const ago = checkInstant(now).getTime() - checkInstant(instant).getTime();
  return ago < 24 * HOUR_MS ? time(instant, timeZone) : day(localDay(instant, timeZone));
}

/** What a district next door posted for a day: "Blue Valley canceled Tuesday". */
function neighborPosted(name: string, status: PostedKey, localDate: string): string {
  const on = weekday(localDate);
  switch (checkKey(copy.status, status, 'status')) {
    case 'closed':
      return `${name} canceled ${on}`;
    case 'delayed':
      return `${name} starts late ${on}`;
    case 'remote':
      return `${name} is remote ${on}`;
    case 'earlyDismissal':
      return `${name} lets out early ${on}`;
  }
}

/** "Shawnee Mission usually announces". */
function usuallyAnnounces(name: string): string {
  return `${name} usually announces`;
}

/** Weather that already happened: "Snow started", "Snow stopped, 8 inches in all". */
function weatherEvent(kind: 'snow_started' | 'snow_stopped', inches: number | null): string {
  if (kind === 'snow_started') return 'Snow started';
  return inches === null ? 'Snow stopped' : `Snow stopped, ${inchWords(inches, inches)} in all`;
}

/** A measure in tenths, without a trailing zero: 7.5, 8. */
function tenths(value: number): string {
  if (!Number.isFinite(value)) throw new RangeError(`copy: ${String(value)} is not a measure`);
  const rounded = Math.round(value * 10) / 10;
  return String(Object.is(rounded, -0) ? 0 : rounded);
}

/** Snow in words: "8 inches", "6 to 9 inches", "1 inch", "0.5 to 1 inch". */
function inchWords(low: number, high: number): string {
  const unit = tenths(high) === '1' ? 'inch' : 'inches';
  return low === high ? `${tenths(high)} ${unit}` : `${tenths(low)} to ${tenths(high)} ${unit}`;
}

/** Snow on the chart: "7.5 in", "6 to 9 in"; the scale's own 0 is "0". */
function inches(low: number, high: number = low): string {
  return low === high ? `${tenths(high)}${NBSP}in` : `${tenths(low)} to ${tenths(high)}${NBSP}in`;
}

/** How cold it feels: "-8 F", "12 F". */
function degrees(value: number): string {
  return `${String(Math.round(value) === 0 ? 0 : Math.round(value))}${NBSP}F`;
}

/** The chart's moments: "Usually announces 5:30 AM", "Buses 7 AM". */
function announcesFlag(instant: Date, timeZone: string): string {
  return `${copy.chance.usuallyAnnounces} ${shortTime(instant, timeZone)}`;
}

function busesFlag(instant: Date, timeZone: string): string {
  return `${copy.chance.buses} ${shortTime(instant, timeZone)}`;
}

/** Beside the lit bars: "Heaviest snow 2 to 5 AM". */
function heaviest(start: Date, end: Date, timeZone: string): string {
  return `${copy.chance.heaviest} ${hourSpan(start, end, timeZone)}`;
}

/** The chart in a sentence, for a screen reader. */
function chartSummary(
  kind: 'snow_total' | 'wind_chill',
  buses: Date,
  low: number,
  high: number,
  timeZone: string,
): string {
  const at = shortTime(buses, timeZone);
  return kind === 'snow_total'
    ? `By ${at}, when the buses run, ${inchWords(low, high)} of snow should be on the ground.`
    : `At ${at}, when the buses run, it will feel like ${degrees(high)}.`;
}

/** The delayed start, as one plain line: "18% chance of a delayed start instead". */
function delayInstead(probability: number): string {
  return `${chance(probability)} chance of a delayed start instead`;
}

/**
 * A share as a count a 12-year-old reads at a glance: "3 in 10", "1 in 4",
 * "13 in 20". The simplest fraction within 2 points of it.
 */
function shareOf(percent: number): { some: number; of: number } {
  if (!Number.isInteger(percent) || percent < 1 || percent > 99) {
    throw new RangeError(`copy: a share is 1 to 99 percent, not ${String(percent)}`);
  }
  for (const whole of [2, 3, 4, 5, 10, 20, 25, 50]) {
    const some = Math.round((percent / 100) * whole);
    if (some >= 1 && some < whole && Math.abs(some / whole - percent / 100) <= 0.02) {
      return { some, of: whole };
    }
  }
  return { some: percent, of: 100 };
}

/** The district's record, counted: "It closed 4 of the last 5 times it got 6 inches or more." */
function recordSentence(record: RecordCount, subject: string): string {
  const { closed, days, inches: least } = record;
  if (!Number.isInteger(days) || days < 1 || !Number.isInteger(closed) || closed > days) {
    throw new RangeError(`copy: ${String(closed)} of ${String(days)} is not a record`);
  }
  const storms = `it got ${inchWords(least, least)} or more`;
  if (days === 1) {
    return closed === 1
      ? `${subject} closed the last time ${storms}.`
      : `${subject} stayed open the last time ${storms}.`;
  }
  const count =
    closed === days
      ? `each of the last ${String(days)}`
      : closed === 0
        ? `none of the last ${String(days)}`
        : `${String(closed)} of the last ${String(days)}`;
  return `${subject} closed ${count} times ${storms}.`;
}

/** "Blue Valley and Olathe", "A, B and C", "A, B and 2 more". */
function names(list: readonly string[]): string {
  if (list.length === 0) throw new RangeError('copy: no names to list');
  if (list.length <= 3) {
    return list.length === 1
      ? (list[0] ?? '')
      : `${list.slice(0, -1).join(', ')} and ${list.at(-1) ?? ''}`;
  }
  return `${list.slice(0, 2).join(', ')} and ${String(list.length - 2)} more`;
}

/** Where the sum starts: "Where we start:" and the district's own rate, as a count. */
function baseReason(input: BaseInput, district: string): Said {
  const { points: percent } = input;
  if (!Number.isInteger(percent) || percent < 0 || percent > 100) {
    throw new RangeError(`copy: a base is 0 to 100 percent, not ${String(percent)}`);
  }
  const extreme = percent === 0 ? 'almost never' : percent === 100 ? 'almost always' : null;
  const share = extreme === null ? shareOf(percent) : null;
  const rate = (noun: string): string =>
    share === null ? '' : `about ${String(share.some)} ${noun}in ${String(share.of)}`;
  let rest: string;
  switch (input.kind) {
    case 'alert': {
      const alerts = ALERT_PLURALS[checkKey(ALERT_PLURALS, input.alert, 'alert')];
      rest =
        extreme === null
          ? `${district} cancels for ${rate('')} ${alerts}.`
          : `${district} ${extreme} cancels for ${alerts}.`;
      break;
    }
    case 'day_after':
      rest =
        extreme === null
          ? `after a snow day, ${district} stays closed the next day ${rate(share?.some === 1 ? 'time ' : 'times ')}.`
          : `after a snow day, ${district} ${extreme} stays closed the next day.`;
      break;
    case 'similar_days':
      rest =
        extreme === null
          ? `on days like this, ${district} closes ${rate(share?.some === 1 ? 'time ' : 'times ')}.`
          : `on days like this, ${district} ${extreme} closes.`;
      break;
  }
  return { lead: copy.chance.start, rest: ` ${rest}` };
}

/** The relation of the heaviest snow to the buses, as the end of its sentence. */
function timingRest(start: Date, end: Date, buses: Date | null, timeZone: string): string {
  const span = hourSpan(start, end, timeZone);
  if (buses === null) return ` falls from ${span}.`;
  const b = buses.getTime();
  if (start.getTime() > b) return ` falls from ${span}, after the buses are out.`;
  if (end.getTime() > b) return ` falls from ${span}, while the buses are out.`;
  if (b - end.getTime() <= 3 * HOUR_MS) return ` falls from ${span}, just before the buses go out.`;
  return ` falls from ${span}, well before the buses go out.`;
}

/**
 * One reason, as a sentence with its bold lead: "A bigger storm than most," and
 * " 6 to 9 inches overnight. It closed 4 of the last 5 times it got 6 inches or more."
 * `district` is the district's short name; `now` and `timeZone` word the times.
 */
function reason(input: ReasonInput, district: string, now: Date, timeZone: string): Said {
  points(input.points);
  switch (input.kind) {
    case 'snow_total': {
      const cited = input.record === null ? '' : ` ${recordSentence(input.record, 'It')}`;
      return {
        lead: input.points > 0 ? 'A bigger storm than most,' : 'A smaller storm than most,',
        rest: ` ${inchWords(input.low, input.high)}${input.overnight ? ' overnight' : ''}.${cited}`,
      };
    }
    case 'record':
      return { lead: `${district}’s record:`, rest: ` ${recordSentence(input.record, 'it')}` };
    case 'neighbors': {
      const { count, status } = input;
      if (!Number.isInteger(count) || count < 1) {
        throw new RangeError(`copy: ${String(count)} districts next door`);
      }
      const verb = input.names === null ? count === 1 : input.names.length === 1;
      const has = verb ? 'has' : 'have';
      const done = {
        closed: 'already canceled',
        delayed: 'already delayed the start',
        remote: 'already gone remote',
        earlyDismissal: 'already called an early dismissal',
      }[checkKey(copy.status, status, 'status')];
      if (input.names === null || input.names.length === 0) {
        return count === 1
          ? { lead: 'A district next door', rest: ` has ${done}.` }
          : { lead: `${String(count)} districts next door`, rest: ` have ${done}.` };
      }
      return { lead: `${names(input.names)},`, rest: ` next door, ${has} ${done}.` };
    }
    case 'timing':
      if (input.end.getTime() <= input.start.getTime()) {
        throw new RangeError('copy: the heaviest snow ends before it starts');
      }
      return {
        lead: 'The heaviest snow',
        rest: timingRest(input.start, input.end, input.buses, timeZone),
      };
    case 'wind_chill':
      return {
        lead: 'The wind',
        rest: ` will make it feel like ${degrees(input.feelsLike)} at the bus stop.`,
      };
    case 'cold':
      return {
        lead: `It will feel like ${degrees(input.feelsLike)}`,
        rest: ` at the bus stop on ${weekday(input.day)} morning.`,
      };
    case 'snow_stops': {
      const at = shortTime(input.at, timeZone);
      if (input.at.getTime() <= now.getTime()) {
        return dayOf(input.at, timeZone) < input.day
          ? {
              lead: `The snow stopped around ${at},`,
              rest: ' so the plows have all day to clear the roads.',
            }
          : {
              lead: `The snow stopped around ${at},`,
              rest: ' which gives the plows a head start.',
            };
      }
      if (input.buses !== null && input.at.getTime() > input.buses.getTime()) {
        return { lead: `The snow keeps falling until ${at},`, rest: ' after the buses go out.' };
      }
      return {
        lead: `The snow should stop by ${at},`,
        rest: ' which gives the plows a head start.',
      };
    }
    case 'sun': {
      return localHour(now, timeZone) < 15
        ? { lead: 'Sun this afternoon', rest: ' will help the salt melt the ice.' }
        : { lead: 'Sun earlier today', rest: ' helped the salt melt the ice.' };
    }
    case 'icy_roads':
      return {
        lead: 'Some side streets could stay icy',
        rest: ` after ${inchWords(input.inches, input.inches)} of snow.`,
      };
    case 'ice':
      return {
        lead: 'Freezing rain',
        rest: ` could leave ${inchWords(input.inches, input.inches)} of ice on the roads.`,
      };
  }
}

/** A day in a district's record, by what it did: "Closed", "Open". */
function recordOutcome(status: StatusKey | 'open'): string {
  return copy.chance[checkKey(copy.chance, status, 'outcome') as 'open'];
}

/** A day in the record for a screen reader: "Closed, Jan 9, 2024, 8 inches". */
function recordDay(status: StatusKey | 'open', localDate: string, snow: number | null): string {
  const said = `${recordOutcome(status)}, ${dayWithYear(localDate)}`;
  return snow === null ? said : `${said}, ${inchWords(snow, snow)}`;
}

export const format = /* @__PURE__ */ deepFreeze({
  weekday,
  chanceOn,
  chanceNumber,
  howWeGot,
  points,
  shortTime,
  hourSpan,
  moved,
  countdown,
  momentTime,
  neighborPosted,
  usuallyAnnounces,
  weatherEvent,
  inches,
  degrees,
  announcesFlag,
  busesFlag,
  heaviest,
  chartSummary,
  delayInstead,
  shareOf,
  baseReason,
  reason,
  recordOutcome,
  recordDay,
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
  grades,
  phone,
  miles,
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

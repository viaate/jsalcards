/**
 * Every customer-facing string in Snowlight lives in this file, or in its
 * formatters' own module (src/copy-format.ts), and nowhere else.
 *
 * - `copy` holds the fixed strings, grouped by where they appear.
 * - `format` (copy-format.ts, which loads with the code that shows it, not
 *   with the page) builds the strings that carry a live value: counts, times,
 *   delays, chances. Its phrasing lives there too, so no component composes words.
 *   The page's shell needs one of them before the rest load, the key's counts:
 *   `shellFormat`, here.
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
// The one the page's first script needs is here; the rest are in copy-format.ts.

/** The locale every formatter writes in. */
export const LOCALE = 'en-US';

let numberFormat: Intl.NumberFormat | undefined;

/** A count, checked: a whole number of 0 or more. */
export function checkCount(n: number, what = 'count'): number {
  if (!Number.isSafeInteger(n) || n < 0) {
    throw new RangeError(`copy: ${what} must be a whole number of 0 or more, not ${String(n)}`);
  }
  return n;
}

/** A whole number with thousands separators: "1,284". */
function number(n: number): string {
  numberFormat ??= new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
  return numberFormat.format(checkCount(n));
}

/**
 * The formatter the page's shell sets the key's counts with, before the rest
 * (`format`, copy-format.ts) load: `format.number` is this same function.
 */
export const shellFormat = /* @__PURE__ */ deepFreeze({ number });

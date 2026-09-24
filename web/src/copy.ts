/**
 * Every customer-facing string in Snowlight lives here, and nowhere else.
 *
 * House style: short, plain, confident, sentence case. No exclamation marks,
 * emoji or em dashes. tests/copy.test.ts enforces the mechanical rules.
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

export const copy = deepFreeze({
  appName: 'Snowlight',
  meta: {
    description: 'Weather school closings and delays across the US, on one map.',
  },
  search: {
    placeholder: 'Search a school, city, or ZIP',
  },
  status: {
    closed: 'Closed',
    delayed: 'Delayed',
    remote: 'Remote',
    earlyDismissal: 'Early dismissal',
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
  days: {
    today: 'Today',
    tomorrow: 'Tomorrow',
  },
  nav: {
    live: 'Live',
    listView: 'List view',
    seasonStats: 'Season stats',
    trackRecord: 'Track record',
    about: 'About',
  },
} as const);

export type Copy = typeof copy;

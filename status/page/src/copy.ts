/** Every sentence the status page shows is written here and nowhere else. `{…}` is filled in. */

export const copy = {
  title: 'Snowlight status',
  brand: 'Snowlight',
  page: 'Status',
  noscript: 'Turn on JavaScript to see the status.',
  description:
    'See whether Snowlight is working right now, and how it has done over the last 90 days.',
  parts: {
    site: { name: 'Website', says: 'snowlightmap.com opens.' },
    closings: {
      name: 'Live school closings',
      says: 'Closings and delays on the map are up to date.',
    },
    chances: {
      name: 'Snow-day chances',
      says: 'Each district’s chance of no school is up to date.',
    },
    accounts: { name: 'Accounts', says: 'Signing in and saved schools.' },
  },
  state: {
    ok: 'Working',
    late: 'Slow or late',
    down: 'Not working',
    unknown: 'Could not check',
    wait: 'Checking',
  },
  banner: {
    wait: 'Checking…',
    first: 'The first check is on its way.',
    firstMore: 'This page fills in within 5 minutes.',
    ok: 'Everything is working.',
    down: 'Not working right now: {parts}.',
    late: 'Slow or late right now: {parts}.',
    unknown: 'We could not check everything just now.',
    stale: 'We have no fresh readings.',
    staleMore: 'The last check was {ago}. Everything below is from then.',
    unreachable: 'We cannot load the status right now.',
    unreachableMore: 'This page tries again every minute.',
    checked: 'Last checked {ago}.',
    kept: 'Could not refresh. This is the check from {ago}.',
  },
  list: { and: '{a} and {b}', comma: '{a}, {b}' },
  heads: {
    now: 'Right now',
    history: 'Last 90 days',
    problems: 'Problems in the last 90 days',
  },
  updated: 'Updated {ago}.',
  share: {
    line: 'Working in {pct} of our checks over {days}.',
    none: 'No readings yet.',
    axisStart: '90 days ago',
    axisEnd: 'Today',
    keyNone: 'No readings',
  },
  day: {
    ok: '{date}: working all day.',
    today: '{date}: working so far today.',
    none: '{date}: no readings.',
    before: '{date}: before checks began.',
    okGap: '{date}: working when checked; no readings for {dur}.',
    mixed: '{date}: {list}.',
    down: 'not working for {dur}',
    late: 'slow or late for {dur}',
    gap: 'no readings for {dur}',
  },
  problem: {
    closed: '{part}: {kind} for {dur}.',
    closedWhen: '{start} to {end}',
    gap: '{part}: {kind} for at least {dur}.',
    gapWhen: 'From {start}. Our readings stopped while it was going on.',
    open: '{part}: {kind} since {start}.',
    openWhen: '{dur} so far.',
    down: 'not working',
    late: 'slow or late',
    none: 'No problems in the last 90 days.',
    noneSince: 'No problems since checks began on {date}.',
    showAll: 'Show all {n}',
    showFewer: 'Show fewer',
  },
  foot: {
    how:
      'Every 5 minutes, a checker that runs apart from the rest of Snowlight looks at each part ' +
      'and keeps what it finds for 90 days. Each bar is one day on the world clock (UTC), so it ' +
      'starts the evening before in the US: 7 p.m. Eastern in winter, 8 p.m. in summer. Times ' +
      'are shown in your time zone.',
    privacy: 'This page uses no cookies and keeps nothing about its visitors.',
    home: 'Go to Snowlight',
  },
  ago: {
    now: 'just now',
    minute: '1 minute ago',
    minutes: '{n} minutes ago',
    hour: '1 hour ago',
    hours: '{n} hours ago',
    days: '{n} days ago',
  },
  dur: {
    minute: '1 minute',
    minutes: '{n} minutes',
    hour: '1 hour',
    hours: '{n} hours',
    day: '1 day',
    days: '{n} days',
    two: '{a} {b}',
  },
} as const;

/** The website the last link goes to. */
export const HOME_URL = 'https://snowlightmap.com/';
/** The address the page is meant to be read at. */
export const CANONICAL_URL = 'https://status.snowlightmap.com/';

/** Fill `{name}` places in a sentence. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  );
}

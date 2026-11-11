/**
 * Every sentence the status page shows is written here and nowhere else. `{…}` is filled in.
 *
 * A line never breaks inside a name, a date or a count: a number is tied to the word after it
 * with a no-break space (`\u00a0`), the words of a part's name and "at least" are tied the
 * same way, and a hyphen inside a name is followed by a word joiner (`\u2060`). The dates and
 * times `view.ts` writes are tied the same way. The two parts of a length are joined by a
 * narrow no-break space (`\u202f`): see `dur.two`.
 */

export const copy = {
  title: 'Snowlight status',
  brand: 'Snowlight',
  page: 'Status',
  noscript: 'Turn on JavaScript to see the status.',
  // Shown in the banner when the page's script has not started 10 seconds after the page opened.
  stuck: 'This page did not finish loading. Reload it to try again.',
  description:
    'See whether Snowlight is working right now, and how it has done over the last 90\u00a0days.',
  parts: {
    // What each part is, never how it is doing: the state beside it says that. A name is one
    // run on a line wherever it is drawn: "Website, Live" must never end a line.
    site: { name: 'Website', says: 'Opening snowlightmap.com.' },
    closings: {
      name: 'Live\u00a0school\u00a0closings',
      says: 'The closings and delays on the map.',
    },
    chances: { name: 'Snow-\u2060day\u00a0chances', says: 'Each district’s chance of no school.' },
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
    // "right now" stays on one line.
    wait: 'Checking…',
    first: 'The first check is on its way.',
    firstMore: 'This page fills in within 5\u00a0minutes.',
    ok: 'Everything is working.',
    down: 'Not working right\u00a0now: {parts}.',
    late: 'Slow or late right\u00a0now: {parts}.',
    unknown: 'We could not check everything just\u00a0now.',
    stale: 'We have no recent checks.',
    // Said with the rows' "Could not check": nothing old is shown as what is true now.
    staleMore: 'The last check was {ago}.',
    unreachable: 'We cannot load the status right now.',
    unreachableMore: 'This page tries again every minute.',
    checked: 'Last checked {ago}.',
    kept: 'Could not refresh. This is the check from {ago}.',
  },
  // "and" stays on the line of the name before it, never on a line of its own.
  list: { and: '{a}\u00a0and {b}', comma: '{a}, {b}' },
  heads: {
    now: 'Right now',
    history: 'Last 90\u00a0days',
    problems: 'Problems in the last 90\u00a0days',
  },
  updated: 'Updated {ago}.',
  share: {
    // {days} is the days the bars count, or under a day after checks began, how long they ran.
    line: 'Working in {pct} of our checks over {days}.',
    none: 'No checks yet.',
    // The checks have begun, and none of this part's has given an answer.
    unknown: 'Could not check so\u00a0far.',
    // The last check is older than every day shown.
    old: 'Not checked in the last 90\u00a0days.',
    unloaded: 'The history could not be loaded.',
    axisStart: '90\u00a0days\u00a0ago',
    axisEnd: 'Today',
    keyNone: 'Not checked',
    keyBefore: 'Before checks began',
    hint: 'Pick a bar to see that day.',
  },
  day: {
    ok: '{date}: working all day.',
    today: '{date}: working so far today.',
    since: '{date}: working since checks began.',
    none: '{date}: not checked.',
    yet: '{date}: not checked yet.',
    before: '{date}: before checks began.',
    okGap: '{date}: working when checked; not checked for {dur}.',
    mixed: '{date}: {list}.',
    down: 'not working for {dur}',
    late: 'slow or late for {dur}',
    gap: 'not checked for {dur}',
  },
  problem: {
    closed: '{part}: {kind} for {dur}.',
    closedWhen: '{start} to {end}',
    gap: '{part}: {kind} for at\u00a0least {dur}.',
    gapWhen: 'From {start}. Our checks stopped while it was going on.',
    open: '{part}: {kind} since {start}.',
    openWhen: '{dur} so\u00a0far.',
    down: 'not working',
    late: 'slow or late',
    none: 'No problems in the last 90\u00a0days.',
    // No recent checks: nothing is said of the time since the last one.
    noneStale: 'No problems up to the last check.',
    noneSince: 'No problems since checks began on {date}.',
    showAll: 'Show all {n}',
    showFewer: 'Show fewer',
  },
  foot: {
    how:
      'Every 5\u00a0minutes, a checker that runs apart from the rest of Snowlight looks at each ' +
      'part and keeps what it finds for 90\u00a0days. Each bar is one day on the world clock, ' +
      'so it starts the evening before in the US: 7\u00a0PM\u00a0Eastern in winter, 8\u00a0PM in ' +
      'summer. Times are shown in your time zone.',
    privacy: 'This page uses no cookies and keeps nothing about its visitors.',
    home: 'Go to Snowlight',
  },
  ago: {
    now: 'just\u00a0now',
    // "ago" stays on the line of its count.
    minute: '1\u00a0minute\u00a0ago',
    minutes: '{n}\u00a0minutes\u00a0ago',
    hour: '1\u00a0hour\u00a0ago',
    hours: '{n}\u00a0hours\u00a0ago',
    days: '{n}\u00a0days\u00a0ago',
  },
  dur: {
    minute: '1\u00a0minute',
    minutes: '{n}\u00a0minutes',
    hour: '1\u00a0hour',
    hours: '{n}\u00a0hours',
    day: '1\u00a0day',
    days: '{n}\u00a0days',
    // "1 hour 10 minutes" is one length: its two parts are joined by a narrow no-break space,
    // which the page draws as a no-break space. Where the whole length is wider than the line
    // (very large text on a narrow phone), it breaks there, between its parts, and nowhere else.
    two: '{a}\u202f{b}',
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

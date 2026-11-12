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
  stuck: 'This page did not finish loading.',
  stuckMore: 'Reload it to try again.',
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
    chances: {
      name: 'Snow-\u2060day\u00a0chances',
      says: 'Each district’s chance of no school.',
    },
    accounts: { name: 'Accounts', says: 'Signing in and saved schools.' },
  },
  // The small mark beside a part's name: its name, said by a screen reader.
  about: 'About {part}',
  state: {
    ok: 'Working',
    late: 'Slow or late',
    down: 'Not working',
    // Where very large text wraps it, "not check" stays together.
    unknown: 'Could not\u00a0check',
    wait: 'Checking',
  },
  banner: {
    // The headline: one short line in the state's color. Which part is in trouble is said in
    // the card under it, and in full to a screen reader (`said`).
    wait: 'Checking…',
    first: 'The first check is on its way.',
    firstMore: 'This page fills in within 5\u00a0minutes.',
    ok: 'Everything is working.',
    down: 'Something is not working.',
    late: 'Something is slow or late.',
    unknown: 'We could not check everything.',
    stale: 'We have no recent checks.',
    // Said with the rows' "Could not check": nothing old is shown as what is true now.
    staleMore: 'The last check was {ago}.',
    unreachable: 'We cannot load the status.',
    unreachableMore: 'This page tries again every minute.',
    checked: 'Last checked {ago}.',
    kept: 'Could not refresh. Checked {ago}.',
  },
  // Said to a screen reader when the headline changes: which parts, by name.
  said: {
    down: 'Not working right\u00a0now: {parts}.',
    late: 'Slow or late right\u00a0now: {parts}.',
  },
  // "and" stays on the line of the name before it, never on a line of its own.
  list: { and: '{a}\u00a0and {b}', comma: '{a}, {b}' },
  heads: {
    now: 'Current status',
    problems: 'Past problems',
  },
  updated: 'Updated {ago}.',
  // A file part's line while its own stamp is not known: before the first check, with no
  // recent checks, when the history did not load, or when the file gave none.
  updatedNone: 'Update time not\u00a0known.',
  share: {
    // Between "90 days ago" and "Today" under the bars: the share of the checks that gave an
    // answer, or, short enough to keep that line one line, why there is none.
    mid: '{pct} of checks working',
    none: 'No checks yet',
    // The checks have begun, and none of this part's has given an answer.
    unknown: 'Could not check',
    // The last check is older than every day shown.
    old: 'No recent checks',
    unloaded: 'Not loaded',
    axisStart: '90\u00a0days\u00a0ago',
    axisEnd: 'Today',
  },
  day: {
    ok: '{date}: working all day.',
    today: '{date}: working so far.',
    since: '{date}: working since checks began.',
    none: '{date}: not checked.',
    yet: '{date}: not checked yet.',
    before: '{date}: before checks began.',
    okGap: '{date}: working when checked; not checked for {dur}.',
    mixed: '{date}: {list}.',
    // The span of a bar in the reader's zone, where it is not the world clock's day.
    span: '{from}\u00a0to {to}',
    down: 'not working for {dur}',
    late: 'slow or late for {dur}',
    gap: 'not checked for {dur}',
  },
  problem: {
    closed: '{part}: {kind} for {dur}.',
    closedWhen: '{start} to {end}',
    // A part's run of problems of one kind on one day, from the first to the last.
    closedMany: '{part}: {kind} {n}\u00a0times, {dur} in\u00a0all.',
    gap: '{part}: {kind} for at\u00a0least {dur}.',
    gapWhen: 'From {start}. Our checks stopped while it was going on.',
    open: '{part}: {kind} since {start}.',
    openWhen: '{dur} so\u00a0far.',
    down: 'not working',
    late: 'slow or late',
    // Under the date of a day with no problem listed that is listed for its gap. A quiet day
    // is not listed at all.
    // The clock's day, while a part could not be checked just now.
    noneUnknown: 'Not every part could be checked.',
    // A day with too few checks to say, or whose checks stopped.
    noneGap: 'This day was not checked in\u00a0full.',
    unchecked: 'Not checked.',
    // Its bars show trouble that no problem listed covers: the summary keeps only the newest.
    unlisted: 'Some problems from this day are not listed.',
    // Both that and too few answers: the two notes as one.
    unlistedGap:
      'Some problems from this day are not listed. This day was not checked in\u00a0full.',
    // A problem still going on, on the day it began; it is told in full under today.
    began: '{part}: {kind} from {time}.',
    going: 'Still going on.',
    // A problem on each day after the one it began on.
    still: '{part}: still {kind} from the day\u00a0before.',
    allDay: 'All day.',
    until: 'Until {time}.',
    untilGap: 'Until {time}, when our checks stopped.',
    // A day the checks can have stayed away on after they stopped on a problem the day before.
    stopped: '{part}: {kind} when our checks stopped on {time}.',
    stoppedWhen: 'This day was not checked in\u00a0full.',
    // After the list, while the first check is inside the 90 days.
    checksBegan: 'Checks began on {start}.',
    cut: 'This list holds the newest {n}\u00a0problems. Older ones are not shown.',
    // Before the first check.
    first: 'No checks yet.',
    // When the history did not load.
    unloaded: 'The history could not be loaded. Reload the page to try again.',
    showOlder: 'Show {n}\u00a0earlier problems',
    showOlderOne: 'Show 1\u00a0earlier problem',
    hideOlder: 'Hide earlier problems',
  },
  foot: {
    how:
      'Every 5\u00a0minutes, a checker that runs apart from the rest of Snowlight looks at each ' +
      'part and keeps what it finds for 90\u00a0days. Each bar is one day on the world clock, ' +
      'so it starts the evening before in the US: 7\u00a0PM\u00a0Eastern in winter, 8\u00a0PM in ' +
      'summer. Times are shown in your time zone.',
    // What each color of bar means.
    key: {
      ok: 'Working',
      late: 'Slow or late',
      down: 'Not working',
      none: 'Not checked',
      before: 'Before checks began',
    },
    share: 'The share under each row counts only the checks that gave an answer.',
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

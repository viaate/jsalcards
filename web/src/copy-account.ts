/**
 * The words of accounts and the admin view: the part of src/copy.ts that
 * loads with the account controls (src/ui/account/) and the admin view
 * (src/admin/), never with the page's first script. The same rules hold here
 * as there, and `npm run lint:copy` reads this file as the site's copy
 * (scripts/check-copy.mjs COPY_MODULES). Names and emails people type are
 * theirs, shown as typed; every fixed word is here.
 */

import { format } from './copy-format.ts';

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

export const accountCopy = /* @__PURE__ */ deepFreeze({
  control: {
    /** The top right of the strip, signed out. */
    signedOut: 'Sign up or log in',
  },
  sheet: {
    signup: 'Sign up',
    login: 'Log in',
    close: 'Close',
    name: 'Name',
    email: 'Email',
    /** Log in takes a username, an email, or the admin’s name. */
    loginField: 'Username or email',
    username: 'Username',
    usernameHint: '3 to 20 letters, numbers or underscores. Others see it next to your number.',
    usernameFree: 'That username is free.',
    checking: 'Checking…',
    password: 'Password',
    over13: 'I am 13 or older',
    ageNote: 'Accounts are for people 13 and older.',
    privacy:
      'Your account keeps your name, email, username and saved schools. Your password never leaves this device. You can delete your account at any time in your settings.',
    createAccount: 'Create account',
    working: 'One moment…',
    toLogin: 'Have an account? Log in',
    toSignup: 'New here? Sign up',
    passwordHint: 'At least 8 characters.',
  },
  /** The view that asks for a username before anything else. */
  username: {
    title: 'Pick a username',
    renamedTitle: 'Pick a new username',
    intro: 'Your account needs a username. Others see it next to your number.',
    renamed: 'Your username was changed. Pick a new one.',
    passwordNote: 'Enter your password once to finish setting up your account.',
    save: 'Save username',
    logout: 'Log out instead',
  },
  menu: {
    mySchools: 'My schools',
    settings: 'Settings',
    admin: 'Admin',
    logout: 'Log out',
  },
  schools: {
    title: 'My schools',
    empty: 'Pin a school from its panel and it shows here, on every device you log in on.',
    remove: 'Remove',
    pinned: 'Pinned',
    full: 'You can keep up to 5 schools. Remove one to add another.',
  },
  settings: {
    title: 'Settings',
    name: 'Name',
    email: 'Email',
    currentPassword: 'Current password',
    newPassword: 'New password',
    passwordForEmail: 'Password, to change your email',
    save: 'Save',
    saved: 'Saved',
    changePassword: 'Change password',
    deleteTitle: 'Delete account',
    deleteNote: 'This deletes your account and your saved schools for good.',
    deleteButton: 'Delete my account',
    privacy:
      'Your account keeps your name, your email, your username and number, your saved schools, and when you signed up and last logged in. Your password never leaves this device: Snowlight keeps only scrambled keys made from it. You can delete your account at any time here, and its name and email go with it.',
    adminNote: 'The admin’s password is set in the repository’s secrets.',
  },
  errors: {
    bad_login: 'That username or email and password don’t match an account.',
    username_length: 'Use 3 to 20 letters, numbers or underscores.',
    username_chars: 'Use only letters, numbers and underscores.',
    username_digits: 'Use at least one letter.',
    username_underscores: 'Start and end with a letter or number, with one underscore at a time.',
    username_reserved: 'That username is reserved. Choose another.',
    username_blocked: 'That username isn’t allowed. Choose another.',
    username_taken: 'Someone already has that username.',
    username_set: 'Your username is already set.',
    needs_rekey: 'Enter your password to finish.',
    email_taken: 'An account already uses that email.',
    too_many: 'Too many tries. Wait 15 minutes, then try again.',
    bad_email: 'Enter an email address.',
    bad_name: 'Enter a name of 1 to 40 characters, without < or >.',
    password_short: 'Use at least 8 characters.',
    password_long: 'Use at most 128 characters.',
    password_common: 'That password is too common. Choose another.',
    over13_required: 'Accounts are for people 13 and older.',
    wrong_password: 'That password isn’t right.',
    network: 'Snowlight can’t be reached right now. Check your connection and try again.',
    server: 'Something went wrong. Try again.',
    signed_out: 'You were logged out. Log in again.',
  },
});

export const adminCopy = /* @__PURE__ */ deepFreeze({
  title: 'Admin',
  back: 'Back to the map',
  tabs: {
    overview: 'Overview',
    statuses: 'Statuses',
    users: 'Users',
    moderation: 'Moderation',
    audit: 'Audit',
  },
  overview: {
    accounts: 'Accounts',
    total: 'All accounts',
    newDay: 'New in the last day',
    newWeek: 'New in the last week',
    activeWeek: 'Logged in this week',
    disabled: 'Disabled',
    chances: 'Chances',
    made: 'Made',
    age: 'Age',
    today: 'Districts at 50% or more today',
    tomorrow: 'Districts at 50% or more tomorrow',
    top: 'Highest chances',
    closings: 'Closings file',
    manual: 'Manual statuses on now',
    busyNetworks: 'Networks with 5 or more sign-ups in a day this week',
    runs: 'Latest runs',
    issues: 'Open watchdog issues',
    none: 'None',
    unread: 'Not readable right now.',
    limited: 'GitHub is limiting reads from this network. Try again in a few minutes.',
    refresh: 'Refresh',
    loading: 'Reading…',
  },
  workflows: {
    predict: 'Chances',
    liveIngest: 'Closings',
    api: 'Accounts service',
    ci: 'Checks',
    preview: 'Site',
  },
  runs: {
    success: 'Passed',
    failure: 'Failed',
    cancelled: 'Cancelled',
    skipped: 'Skipped',
    running: 'Running',
    queued: 'Queued',
    other: 'Finished',
    never: 'No runs yet',
  },
  statuses: {
    find: 'Find a school or district',
    published: 'On the map now',
    nothing: 'No status',
    chance: 'Chance today',
    set: 'Set a status',
    scope: 'For',
    district: 'The whole district',
    school: 'This school only',
    status: 'Status',
    closed: 'Closed',
    delayed: 'Delayed',
    earlyDismissal: 'Early dismissal',
    open: 'Open',
    minutes: 'Minutes late',
    time: 'Dismissal time',
    days: 'Days, in its own time zone',
    today: 'Today',
    tomorrow: 'Tomorrow',
    both: 'Today and tomorrow',
    replaces: 'Saving replaces its manual status, days and all.',
    note: 'Note, only admins see it',
    save: 'Set status',
    active: 'Manual statuses',
    noneActive: 'No manual statuses are on.',
    clear: 'Clear',
    waiting: 'Waiting to publish',
    onMap: 'On the map',
    shadowed: 'Each school has its own status',
    pickAgain: 'The school’s date has changed. Pick its days again.',
    noZone: 'Its time zone is not readable right now, so a status cannot be set for it yet.',
    expired: 'Ended',
    pickFirst: 'Find a school or district first.',
  },
  users: {
    search: 'Find by name, username or email',
    name: 'Name',
    username: 'Username',
    noUsername: 'Not picked yet',
    renamePending: 'Picks a new one at next sign-in',
    rename: 'Rename',
    renameTo: 'New username, or empty for a player number',
    renameSave: 'Rename',
    renameCancel: 'Cancel',
    renameBlock: 'Also block this word for everyone',
    renameBlocked:
      'Renamed. Their old name is now blocked for everyone, with any letters or numbers around it.',
    renameTooShort: 'Renamed. Their old name is too short to block as a word.',
    renameFull: 'Renamed. Their old name is not blocked: you have 50 words of that kind.',
    email: 'Email',
    created: 'Joined',
    lastLogin: 'Last login',
    schools: 'Saved schools',
    state: 'State',
    active: 'Active',
    disabled: 'Disabled',
    reset: 'Reset password',
    disable: 'Disable',
    enable: 'Enable',
    delete: 'Delete',
    confirmDelete: 'Delete for good',
    temporary: 'Temporary password, shown once. Give it to them and ask them to change it:',
    none: 'No accounts match.',
    more: 'Next page',
    less: 'Previous page',
    adminRow: 'Admin',
  },
  moderation: {
    intro:
      'The built-in list blocks slurs, sexual words, hate, self-harm and drug terms, and their spellings with numbers, repeats, underscores or backwards. Add your own here; they apply at once.',
    builtIn: 'Built-in list',
    term: 'Word or part of a word',
    kind: 'Match',
    substring: 'Anywhere in a name',
    token: 'Only as a whole word',
    raw: 'A number code anywhere',
    allow: 'Always allowed',
    full: 'You have 50 words of this kind. Remove one to add another.',
    add: 'Add',
    added: 'Your words',
    none: 'No words added yet.',
    remove: 'Remove',
    scanning: 'Checking every username…',
    caught: 'Usernames it catches',
    caughtAll: 'Usernames the lists catch now',
    noneCaught: 'No username matches.',
    scanAll: 'Check every username',
    rename: 'Rename to a player number',
    renamed: 'Renamed',
  },
  audit: {
    when: 'When',
    who: 'Who',
    what: 'What',
    target: 'Target',
    none: 'Nothing logged yet.',
    deletedUser: 'Deleted user',
  },
  errors: {
    forbidden: 'This view is for the admin.',
    failed: 'That didn’t work. Try again.',
  },
});

/** "Account menu for Sam": the signed-in control, for a screen reader. */
function menuLabel(name: string): string {
  return `Account menu for ${name}`;
}

/** The first word of a name, for the strip: "Sam" of "Sam Rivera". */
function firstName(name: string): string {
  const first = name.trim().split(/\s+/u)[0] ?? '';
  return first.length > 0 ? first : name;
}

/** "Open Lincoln Elementary": a saved school's button. */
function openSchool(name: string): string {
  return `Open ${name}`;
}

/** "Remove Lincoln Elementary": a saved school's remove button, for a screen reader. */
function removeSchool(name: string): string {
  return `Remove ${name}`;
}

/** "Delayed 120 minutes", "Early dismissal at 13:30", for a manual status row. */
function manualStatus(status: string, minutes: number | null, at: string | null): string {
  switch (status) {
    case 'closed':
      return 'Closed';
    case 'delayed':
      return minutes === null ? 'Delayed' : `Delayed ${format.number(minutes)} minutes`;
    case 'early_dismissal':
      return at === null ? 'Early dismissal' : `Early dismissal at ${at}`;
    case 'open':
      return 'Open';
    default:
      throw new RangeError(`copy: no manual status ${status}`);
  }
}

/** "District 3904378", "School 390437801234": a manual status's target by id. */
function target(scope: string, id: string): string {
  return `${scope === 'district' ? 'District' : 'School'} ${id}`;
}

/** "Page 2 of 5". */
function page(n: number, of: number): string {
  return `Page ${format.number(n)} of ${format.number(Math.max(1, of))}`;
}

/** An age in words: "4 min", "3 h", "2 d". */
function age(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  if (minutes < 60) return `${format.number(minutes)} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${format.number(hours)} h`;
  return `${format.number(Math.round(hours / 24))} d`;
}

/** "Delete the account for sam@example.com?" */
function confirmDelete(who: string): string {
  return `Delete the account for ${who}?`;
}

/** An instant in the viewer's time zone: "5:42 PM" today, else "Mon, Oct 19, 5:42 PM". */
function when(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) throw new RangeError('copy: not an instant');
  let zone = 'UTC';
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    // UTC stands in.
  }
  const time = format.time(at, zone);
  const local = format.localDay(at, zone);
  return local === format.localDay(now, zone) ? time : `${format.day(local)}, ${time}`;
}

/** "Tue, Oct 20": one of a manual status's days, a local date. */
function listedDay(localDate: string): string {
  return format.day(localDate);
}

/** "203.0.113.0/24: 7 sign-ups on Tue, Oct 20": a network that made many accounts in one UTC day. */
function busyNetwork(network: string, count: number, utcDate: string): string {
  return `${network}: ${format.number(count)} sign-ups on ${format.day(utcDate)}`;
}

/** "Today (Tue, Oct 20)": a day the form offers, with its date in the school's zone. */
function dayChoice(label: string, localDate: string): string {
  return `${label} (${format.day(localDate)})`;
}

/** "Today and tomorrow (Wed, Oct 21 and Thu, Oct 22)": both days, with their dates. */
function bothChoice(label: string, today: string, tomorrow: string): string {
  return `${label} (${format.day(today)} and ${format.day(tomorrow)})`;
}

/** A chance as a whole percent: "72%". */
function percent(p: number): string {
  return `${format.number(Math.round(p * 100))}%`;
}

/** "3 accounts". */
function accounts(n: number): string {
  return `${format.number(n)} ${n === 1 ? 'account' : 'accounts'}`;
}

/** What an audit entry did, in words. */
function action(code: string): string {
  const words: Record<string, string> = {
    admin_login: 'Admin logged in',
    set_status: 'Set a status',
    clear_status: 'Cleared a status',
    reset_password: 'Reset a password',
    disable_user: 'Disabled an account',
    enable_user: 'Enabled an account',
    delete_user: 'Deleted an account',
    rename_user: 'Renamed an account',
    add_term: 'Added a blocked word',
    remove_term: 'Removed a blocked word',
  };
  return words[code] ?? 'Other change';
}

/** A join number as its box shows it: "#0042". */
function joinNumber(n: number): string {
  return `#${String(n).padStart(4, '0')}`;
}

/** "frosty_fox, number 42": a username and its box, for a screen reader. */
function userTag(username: string, n: number | null): string {
  return n === null ? username : `${username}, number ${format.number(n)}`;
}

/** "3 usernames checked". */
function scanned(n: number): string {
  return `${format.number(n)} ${n === 1 ? 'username' : 'usernames'} checked`;
}

export const accountFormat = /* @__PURE__ */ deepFreeze({
  joinNumber,
  userTag,
  scanned,
  menuLabel,
  firstName,
  openSchool,
  removeSchool,
  manualStatus,
  target,
  page,
  age,
  confirmDelete,
  accounts,
  action,
  percent,
  when,
  listedDay,
  dayChoice,
  bothChoice,
  busyNetwork,
  number: (n: number): string => format.number(n),
});

export type AccountCopy = typeof accountCopy;
export type AccountErrorCode = keyof AccountCopy['errors'];

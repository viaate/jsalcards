/** From the summary and a clock to what the page says. Pure: no DOM, no fetch, no timer. */

import { INCIDENTS_MAX, barOf, dayStart, expected, shareOf } from '../../shared/history.ts';
import type { BarClass } from '../../shared/history.ts';
import { DAY, DAYS_KEPT, PARTS, TICK } from '../../shared/types.ts';
import type { Part, State, Summary, SummaryIncident } from '../../shared/types.ts';
import { copy, fill } from './copy.ts';

/** With no summary newer than this many seconds, the page says it has no fresh readings. */
export const STALE_AFTER = 900;
/** The page asks again this long after a summary's tick: the next tick, and 45 s for its write. */
export const NEXT_AFTER = 345;
export const RETRY_AFTER = 60;
export const STALE_RETRY_AFTER = 300;
/**
 * "Past problems" lists the problem days of this many days at most, the clock's own and those
 * before it, and never a day before the one the checks began on. A day with no problem is not
 * listed at all.
 */
export const DAYS_LISTED = 15;
/**
 * A day counts as checked in full only while each part has at most this
 * many checks with no answer in it (10 minutes); from one more on, it says it was not. Each
 * part is counted at the most it can be from the bars: in each UTC bar the day touches, the
 * fewer of the bar's checks with no answer and the day's own checks in that bar. The store
 * keeps a count a UTC day, not when in it the checks had no answer, so a day that shares a UTC
 * bar with its neighbour can be counted the neighbour's: any lower count could leave a day out
 * of "Past problems" as quiet over checks that had no answer on that very day.
 */
export const UNANSWERED_ALLOWED = 2;
/** A part's problems of one kind that ended on the day they began are told as one from this many. */
export const RUN_TOLD_AS_ONE = 3;

/** The two parts that are files with a stamp of their own. */
const FILES: readonly Part[] = ['closings', 'chances'];

export interface Picked {
  part: Part;
  /** The bar, 0 (90 days ago) to 89 (today). */
  day: number;
}

export type Input =
  | { kind: 'wait' }
  | { kind: 'unreachable' }
  | {
      kind: 'data';
      /** Null: the checker has not written yet. */
      summary: Summary | null;
      /** The server's clock, carried forward: Unix seconds. */
      clock: number;
      /** The last refresh failed: what is shown is an older answer. */
      kept: boolean;
      expanded: boolean;
      picked: Picked | null;
      /** The time zone a problem's times are said in; left out: the visitor's. */
      zone?: string;
    };

export type Shape = State | 'wait';

export interface BarView {
  /**
   * `yet`: the day has begun and its first check is not due; nothing is drawn. `unloaded`: the
   * status could not be loaded, so no day is known; the row is an empty outline.
   */
  cls: BarClass | 'wait' | 'yet' | 'unloaded';
  /** The bar's name; null while there is nothing to name. */
  label: string | null;
  picked: boolean;
}

/** A problem as "Past problems" lists it: its heading in its kind's color, and its times. */
export interface ProblemView {
  kind: 'late' | 'down';
  what: string;
  when: string;
}

/**
 * A day in "Past problems": its date, and its problems or, on a day with none listed that was
 * not checked in full, the note said in their place.
 */
export interface DayView {
  /** 'Wed, Nov 11', in the reader's zone. */
  date: string;
  /** Each problem that covered any of the day, the ones still going on first. */
  problems: ProblemView[];
  /** Null when the day has problems. */
  none: string | null;
  /** Under a day's problems: that its bars show trouble no listed problem covers. */
  note: string | null;
}

export interface View {
  banner: {
    shape: Shape;
    /** The headline: one short line. */
    lead: string;
    /** What a screen reader is told when the headline changes: the parts by name. */
    said: string;
    more: string | null;
    /** While it waits: what the banner says if the page's script never starts. */
    stuck: { lead: string; more: string } | null;
  };
  parts: {
    part: Part;
    name: string;
    says: string;
    shape: Shape;
    word: string;
    /** A file part has an "Updated" line (empty while the page waits); the others have none. */
    file: boolean;
    updated: string;
  }[];
  history: {
    part: Part;
    name: string;
    /** Between "90 days ago" and "Today": the share, or why there is none; empty while it waits. */
    mid: string;
    bars: BarView[];
    /** The picked bar's name, shown in a tip over the bars; null: no bar is picked. */
    note: string | null;
  }[];
  problems: {
    /**
     * The days with a problem of the last `DAYS_LISTED` back to the day the checks began,
     * newest first; a quiet day is left out. Empty while there is no history to list.
     */
    days: DayView[];
    /** Said in place of the days when there is no history: why. Null while it waits. */
    empty: string | null;
    /** The problem days before them, newest first, shown when `expanded`. */
    older: DayView[];
    button: string | null;
    expanded: boolean;
    /** When the checks began, said after the list while that is inside the 90 days. */
    began: string | null;
    /** The summary holds only the newest problems: said when it is full. */
    cut: string | null;
  };
}

/** Two readings of the device's clocks, in milliseconds: `performance.now()` and `Date.now()`. */
export interface Marks {
  perf: number;
  date: number;
}

/**
 * Seconds since `then`: the larger of the two differences. A sleeping device can stop the
 * first clock, and a wrong device clock cancels out of the second.
 */
export function elapsed(then: Marks, now: Marks): number {
  return Math.max(0, now.perf - then.perf, now.date - then.date) / 1000;
}

/** How many seconds after an answer the page asks again. */
export function nextDelay(good: boolean, summary: Summary | null, clock: number): number {
  if (!good || summary === null) return RETRY_AFTER;
  if (clock - summary.now > STALE_AFTER) return STALE_RETRY_AFTER;
  return Math.min(NEXT_AFTER, Math.max(RETRY_AFTER, summary.now + NEXT_AFTER - clock));
}

/** An answer of `/api/status` the page can draw, or null. */
export function readAnswer(
  status: number,
  body: unknown,
): { served: number; summary: Summary | null } | null {
  if (status !== 200 || typeof body !== 'object' || body === null) return null;
  const { served, summary } = body as { served?: unknown; summary?: unknown };
  if (typeof served !== 'number' || !Number.isFinite(served)) return null;
  if (summary === null) return { served, summary: null };
  if (typeof summary !== 'object' || (summary as { v?: unknown }).v !== 1) return null;
  return { served, summary: summary as Summary };
}

export function ago(seconds: number): string {
  if (seconds < 60) return copy.ago.now;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes === 1 ? copy.ago.minute : fill(copy.ago.minutes, { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return hours === 1 ? copy.ago.hour : fill(copy.ago.hours, { n: hours });
  return fill(copy.ago.days, { n: Math.floor(hours / 24) });
}

function count(n: number, one: string, many: string): string {
  return n === 1 ? one : fill(many, { n });
}

/** A length of time, rounded down to the minute: one unit, or two with a zero part left out. */
export function dur(seconds: number): string {
  const minutes = Math.max(1, Math.floor(seconds / 60));
  const m = count(minutes % 60, copy.dur.minute, copy.dur.minutes);
  if (minutes < 60) return m;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const h = count(hours, copy.dur.hour, copy.dur.hours);
    return minutes % 60 === 0 ? h : fill(copy.dur.two, { a: h, b: m });
  }
  // From 48 hours on, never one day.
  const d = fill(copy.dur.days, { n: Math.floor(hours / 24) });
  const h = count(hours % 24, copy.dur.hour, copy.dur.hours);
  return hours % 24 === 0 ? d : fill(copy.dur.two, { a: d, b: h });
}

/** "A", "A and B", "A, B and C". */
export function listed(names: readonly string[]): string {
  if (names.length === 0) return '';
  if (names.length === 1) return names[0]!;
  const head = names.slice(0, -1).reduce((a, b) => fill(copy.list.comma, { a, b }));
  return fill(copy.list.and, { a: head, b: names[names.length - 1]! });
}

/** A no-break space: a line never breaks inside a date, a time or a count. */
const NB = '\u00a0';

const UTC_DAY = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

/** 'Tue, Nov 3': a bar's UTC day, the month tied to its day. */
function utcDay(t: number): string {
  const parts = new Map(UTC_DAY.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  return `${parts.get('weekday')}, ${parts.get('month')}${NB}${parts.get('day')}`;
}

/** One formatter a zone, made once: every bar's tip names its span. */
const LOCALS = new Map<string, Intl.DateTimeFormat>();

interface Local {
  date: string;
  time: string;
  zone: string;
}

/**
 * An instant in the reader's zone: 'Nov 7', '6:10 AM', 'EST'. The month is tied to its day and
 * the time to its AM or PM; `zoned` ties the zone on.
 */
function local(t: number, zone: string | undefined): Local {
  let format = LOCALS.get(zone ?? '');
  if (format === undefined) {
    format = new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short',
      timeZone: zone,
    });
    LOCALS.set(zone ?? '', format);
  }
  const parts = new Map(format.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  return {
    date: `${parts.get('month')}${NB}${parts.get('day')}`,
    time: `${parts.get('hour')}:${parts.get('minute')}${NB}${parts.get('dayPeriod')}`,
    zone: parts.get('timeZoneName') ?? '',
  };
}

/** 'Nov 7, 6:10 AM EST': breaks only after the comma. */
function zoned(at: Local): string {
  return `${at.date}, ${at.time}${NB}${at.zone}`;
}

/**
 * The span a bar covers, in the reader's zone: 'Nov 1, 7:00 PM to Nov 2, 7:00 PM EST', so a
 * tip never names a date that "Past problems" uses for a different span. Where the reader's
 * clock is the world clock all day, the bar's day is the reader's own: 'Mon, Nov 2'.
 */
function barSpan(start: number, zone: string | undefined): string {
  if (offsetAt(start, zone) === 0 && offsetAt(start + DAY, zone) === 0) return utcDay(start);
  const from = local(start, zone);
  const to = local(start + DAY, zone);
  return fill(copy.day.span, {
    from: from.zone === to.zone ? `${from.date}, ${from.time}` : zoned(from),
    to: zoned(to),
  });
}

/** 'From' to 'to' of a problem, or of a run of them: the end's date only when it differs. */
function between(start: number, end: number, zone: string | undefined): string {
  const from = local(start, zone);
  const to = local(end, zone);
  return fill(copy.problem.closedWhen, {
    // Both zones are named when the clocks changed in between.
    start: to.zone === from.zone ? `${from.date}, ${from.time}` : zoned(from),
    end: `${to.date === from.date ? '' : `${to.date}, `}${to.time}${NB}${to.zone}`,
  });
}

/** What a bar's name is made from. */
interface DayFacts {
  /** The first second of the bar's UTC day. */
  start: number;
  counts: readonly [number, number, number];
  /** The checks the day should hold: from the first check ever, and from the day's start. */
  e: number;
  whole: number;
  /** The day is the clock's own. */
  today: boolean;
  /** The day began after the last check: nothing can be known of it yet. */
  yet: boolean;
  /** The reader's zone; left out: the visitor's. */
  zone: string | undefined;
}

/** The day has begun, its first check is not due, and the last check is not old: no bar yet. */
function notDue(e: number, yet: boolean): boolean {
  return e === 0 && yet;
}

/**
 * A bar's name. "All day" is said only of a day checked from its first tick to its last, and
 * "today" only of the clock's own day: a day the checks began in says so, and its time with
 * no check is counted from the day's start once there is any to say.
 */
function dayText({ start, counts, e, whole, today, yet, zone }: DayFacts): string {
  const date = barSpan(start, zone);
  const bar = barOf(counts, e);
  if (bar.e === 0) return fill(notDue(e, yet) ? copy.day.yet : copy.day.before, { date });
  if (bar.k === 0) return fill(copy.day.none, { date });
  const [, late, down] = counts;
  const began = whole > e;
  const unchecked = Math.max(0, whole - bar.k);
  const missing = dur(unchecked * TICK);
  if (late === 0 && down === 0) {
    if (bar.m > 0) return fill(copy.day.okGap, { date, dur: missing });
    if (began) return fill(copy.day.since, { date });
    return fill(today ? copy.day.today : copy.day.ok, { date });
  }
  const list: string[] = [];
  if (down > 0) list.push(fill(copy.day.down, { dur: dur(down * TICK) }));
  if (late > 0) list.push(fill(copy.day.late, { dur: dur(late * TICK) }));
  if (unchecked > 0) list.push(fill(copy.day.gap, { dur: missing }));
  return fill(copy.day.mixed, {
    date,
    list: list.reduce((a, b) => fill(copy.list.comma, { a, b })),
  });
}

/**
 * When a problem ended, as far as the page can say, and whether the checks stopped on it. With
 * no fresh readings an open one is drawn as one whose readings stopped, a tick after its last.
 */
function ending(incident: SummaryIncident, stale: boolean): { end: number | null; gap: boolean } {
  if (incident.e === null && stale) return { end: (incident.l ?? incident.s) + TICK, gap: true };
  return { end: incident.e, gap: incident.g === 1 };
}

function problemText(
  incident: SummaryIncident,
  clock: number,
  stale: boolean,
  zone: string | undefined,
  unknownNow: boolean,
): ProblemView {
  const part = copy.parts[incident.p].name;
  const kind = incident.k === 'down' ? copy.problem.down : copy.problem.late;
  const from = local(incident.s, zone);
  const { end, gap } = ending(incident, stale);
  if (end === null) {
    return {
      kind: incident.k,
      what: fill(copy.problem.open, { part, kind, start: zoned(from) }),
      // While the part's newest check could not tell, the length stops at its last reading:
      // no time the checker did not see is counted as part of the problem.
      when: fill(copy.problem.openWhen, {
        dur: dur((unknownNow ? (incident.l ?? incident.s) + TICK : clock) - incident.s),
      }),
    };
  }
  if (gap) {
    return {
      kind: incident.k,
      what: fill(copy.problem.gap, { part, kind, dur: dur(end - incident.s) }),
      when: fill(copy.problem.gapWhen, { start: zoned(from) }),
    };
  }
  return {
    kind: incident.k,
    what: fill(copy.problem.closed, { part, kind, dur: dur(end - incident.s) }),
    when: between(incident.s, end, zone),
  };
}

function waiting(input: Input): View {
  const first = input.kind === 'data';
  const unreachable = input.kind === 'unreachable';
  const shape: Shape = unreachable ? 'unknown' : 'wait';
  let lead: string = copy.banner.wait;
  let more: string | null = null;
  if (first) {
    lead = copy.banner.first;
    more = copy.banner.firstMore;
  } else if (unreachable) {
    lead = copy.banner.unreachable;
    more = copy.banner.unreachableMore;
  }
  // Not loaded is never drawn as days before the checks began: the key names that color.
  const bars: BarView[] = Array.from({ length: DAYS_KEPT }, () => ({
    cls: unreachable ? 'unloaded' : 'wait',
    label: null,
    picked: false,
  }));
  return {
    // Only the page as built can be left waiting for a script that never starts.
    banner: {
      shape,
      lead,
      said: lead,
      more,
      stuck: input.kind === 'wait' ? { lead: copy.stuck, more: copy.stuckMore } : null,
    },
    parts: PARTS.map((part) => ({
      part,
      name: copy.parts[part].name,
      says: copy.parts[part].says,
      shape,
      word: copy.state[shape],
      file: FILES.includes(part),
      updated: input.kind === 'wait' || !FILES.includes(part) ? '' : copy.updatedNone,
    })),
    history: PARTS.map((part) => ({
      part,
      name: copy.parts[part].name,
      mid: first ? copy.share.none : unreachable ? copy.share.unloaded : '',
      bars,
      note: null,
    })),
    problems: {
      days: [],
      // No history must not read as "there were none".
      empty: first ? copy.problem.first : unreachable ? copy.problem.unloaded : null,
      older: [],
      button: null,
      expanded: false,
      began: null,
      cut: null,
    },
  };
}

/** What the page says for an input. */
export function viewOf(input: Input): View {
  if (input.kind !== 'data' || input.summary === null) return waiting(input);
  const { summary, clock } = input;
  const stale = clock - summary.now > STALE_AFTER;
  const sinceCheck = ago(clock - summary.now);

  const names = (state: State): string[] =>
    PARTS.filter((part) => summary.parts[part].s === state).map((part) => copy.parts[part].name);
  const down = names('down');
  const late = names('late');
  let shape: Shape;
  let lead: string;
  let said: string | null = null;
  let more: string;
  if (stale) {
    shape = 'unknown';
    lead = copy.banner.stale;
    more = fill(copy.banner.staleMore, { ago: sinceCheck });
  } else {
    const named: string[] = [];
    if (down.length > 0) named.push(fill(copy.said.down, { parts: listed(down) }));
    if (late.length > 0) named.push(fill(copy.said.late, { parts: listed(late) }));
    if (named.length > 0) said = named.join(' ');
    if (down.length > 0) {
      shape = 'down';
      lead = copy.banner.down;
    } else if (late.length > 0) {
      shape = 'late';
      lead = copy.banner.late;
    } else if (names('unknown').length > 0) {
      shape = 'unknown';
      lead = copy.banner.unknown;
    } else {
      shape = 'ok';
      lead = copy.banner.ok;
    }
    more = fill(input.kept ? copy.banner.kept : copy.banner.checked, {
      ago: sinceCheck,
    });
  }

  const parts = PARTS.map((part) => {
    const now = summary.parts[part];
    const state: State = stale ? 'unknown' : now.s;
    const made = stale ? undefined : now.made;
    return {
      part,
      name: copy.parts[part].name,
      says: copy.parts[part].says,
      shape: state as Shape,
      word: copy.state[state],
      file: FILES.includes(part),
      updated: !FILES.includes(part)
        ? ''
        : made === undefined
          ? copy.updatedNone
          : fill(copy.updated, { ago: ago(clock - made) }),
    };
  });

  // The last bar is always the clock's own UTC day, so "Today" and "90 days ago" stay true:
  // when the summary's last day is behind it, the bars move up and the days since have no check.
  const at = Math.max(clock, summary.now);
  const today = Math.floor(at / DAY) * DAY;
  /** The first second of the oldest day shown. */
  const from = today - (DAYS_KEPT - 1) * DAY;
  /** How many days the summary's last day is behind the clock's: that many bars have no count. */
  const behind = Math.min(DAYS_KEPT, (from - dayStart(summary.from)) / DAY);
  const starts = Array.from({ length: DAYS_KEPT }, (_, i) => from + i * DAY);
  /**
   * The instant a day's checks are counted to. A past day: its end. The clock's day: the
   * summary's own tick (the clock runs up to a tick ahead of it), and the clock once stale.
   */
  const until = (start: number): number => (start === today && !stale ? summary.now : at);
  /** Each part's counts a bar, the bars moved up to the clock's day. */
  const tallies = Object.fromEntries(
    PARTS.map((part) => [
      part,
      [
        ...summary.days[part].slice(behind),
        ...Array.from({ length: behind }, () => [0, 0, 0] as const),
      ],
    ]),
  ) as Record<Part, (readonly [number, number, number])[]>;
  const history = PARTS.map((part) => {
    const counts = tallies[part];
    const bars = counts.map((triple, i): BarView => {
      const start = starts[i]!;
      const e = expected(start, summary.first, until(start));
      const yet = start > summary.now;
      return {
        // A day with no check due yet is not drawn as one before the checks began.
        cls: notDue(e, yet) ? 'yet' : barOf(triple, e).cls,
        label: dayText({
          start,
          counts: triple,
          e,
          whole: expected(start, 0, until(start)),
          today: start === today,
          yet,
          zone: input.zone,
        }),
        picked: input.picked !== null && input.picked.part === part && input.picked.day === i,
      };
    });
    // The share is of the checks made: the days it names end at the summary's own tick.
    const share = shareOf(
      counts,
      starts.map((start) => expected(start, summary.first, summary.now)),
    );
    // No reading to take a share of: either no check of this part gave an answer, or the last
    // check is older than every day shown. "No checks yet" is said only before the first check.
    let mid: string = share.days === 0 ? copy.share.old : copy.share.unknown;
    if (share.pct !== null) mid = fill(copy.share.mid, { pct: share.pct });
    return {
      part,
      name: copy.parts[part].name,
      mid,
      bars,
      note: bars.find((bar) => bar.picked)?.label ?? null,
    };
  });

  const cells = Object.fromEntries(
    history.map((block) => [block.part, block.bars.map((bar) => bar.cls)]),
  ) as Record<Part, BarView['cls'][]>;
  const problems = pastProblems(summary, input, stale, starts, cells, tallies);
  return {
    banner: { shape, lead, said: said ?? lead, more, stuck: null },
    parts,
    history,
    problems,
  };
}

/** The reader's wall clock at an instant: one formatter a zone, made once. */
const WALLS = new Map<string, Intl.DateTimeFormat>();

function wall(
  t: number,
  zone: string | undefined,
): [number, number, number, number, number, number] {
  const name = zone ?? '';
  let format = WALLS.get(name);
  if (format === undefined) {
    format = new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hourCycle: 'h23',
      timeZone: zone,
    });
    WALLS.set(name, format);
  }
  const parts = new Map(format.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  const n = (type: Intl.DateTimeFormatPartTypes): number => Number(parts.get(type));
  return [n('year'), n('month'), n('day'), n('hour') % 24, n('minute'), n('second')];
}

/** 'YYYY-MM-DD' of an instant in a zone: days are told apart, and ordered, by their keys. */
function dayKey(t: number, zone: string | undefined): string {
  const [y, m, d] = wall(t, zone);
  return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

/** Seconds the zone's wall clock is ahead of UTC at an instant. */
function offsetAt(t: number, zone: string | undefined): number {
  const [y, m, d, h, mi, s] = wall(t, zone);
  return Date.UTC(y, m - 1, d, h, mi, s) / 1000 - t;
}

/** The key and the heading of the day `back` days before a day key. */
function dayBefore(key: string, back: number): { key: string; date: string } {
  const [y, m, d] = key.split('-').map(Number) as [number, number, number];
  const t = Date.UTC(y, m - 1, d - back, 12) / 1000;
  return { key: dayKey(t, 'UTC'), date: utcDay(t) };
}

/** The first second of a day key in the reader's zone (its midnight, or its first hour). */
function keyStart(key: string, zone: string | undefined): number {
  const [y, m, d] = key.split('-').map(Number) as [number, number, number];
  const t = Date.UTC(y, m - 1, d) / 1000;
  const guess = t - offsetAt(t, zone);
  return t - offsetAt(guess, zone);
}

/** A problem with the instants it covers, as far as the page can say. */
interface Span {
  incident: SummaryIncident;
  /** The instant after its last: its end, or the clock while it is open. */
  to: number;
  open: boolean;
  gap: boolean;
  /** The day it is told in full on: the day it began, or the first day of the list's range. */
  home: string;
  /** It began on its home day, not before the list's range. */
  here: boolean;
  full: ProblemView;
  /** Ended by a gap: the latest the checks can have stayed away after it, from the bars. */
  away: number;
}

/** One line of a day in "Past problems", and whether it is a whole problem of that day. */
interface Told {
  span: Span;
  view: ProblemView;
  whole: boolean;
}

/**
 * "Past problems": the days in the reader's zone from the clock's own back `DAYS_LISTED` days,
 * never before the day the checks began, newest first. Each day lists every problem that
 * covered any of it: in full on the day it began (an open one in full on the clock's day, and
 * from its time on the day it began), and as still going on for each day after. A day with no
 * problem is not listed, and only where every part was checked and every bar of trouble that
 * touches it is one of the listed problems: a day with too few checks is listed with a note
 * that says so, and a day whose bars show trouble no listed problem covers (the summary holds
 * the newest `INCIDENTS_MAX` only) with one that says problems are missing. The problem days
 * before, back to the first of the 90 bars, are behind the button.
 */
function pastProblems(
  summary: Summary,
  input: Extract<Input, { kind: 'data' }>,
  stale: boolean,
  starts: readonly number[],
  cells: Readonly<Record<Part, readonly BarView['cls'][]>>,
  tallies: Readonly<Record<Part, readonly (readonly [number, number, number])[]>>,
): View['problems'] {
  const { clock, zone } = input;
  const at = Math.max(clock, summary.now);
  const from = starts[0]!;
  const today = dayKey(at, zone);
  const firstDay = dayKey(summary.first, zone);
  const lastDay = dayKey(summary.now, zone);
  /** The oldest day any of the 90 bars touches. */
  const rangeStart = dayKey(Math.max(from, summary.first), zone);
  const unknownNow = PARTS.some((part) => summary.parts[part].s === 'unknown');

  /** The checks due in [lo, hi): the ticks from the first check to the summary's last. */
  const dueIn = (lo: number, hi: number): number => {
    const a = Math.max(Math.ceil(lo / TICK), Math.ceil(summary.first / TICK));
    const b = Math.min(Math.ceil(hi / TICK) - 1, Math.floor(summary.now / TICK));
    return b < a ? 0 : b - a + 1;
  };
  /** Each bar's checks with no answer, of those due up to the summary's last tick. */
  const missed = {} as Record<Part, number[]>;
  for (const part of PARTS) {
    missed[part] = starts.map((start, i) => {
      const [ok, late, down] = tallies[part][i] ?? [0, 0, 0];
      return Math.max(0, dueIn(start, start + DAY) - ok - late - down);
    });
  }
  /** The most of a part's checks due in [lo, hi) that can have had no answer. */
  const unanswered = (part: Part, lo: number, hi: number): number => {
    let n = 0;
    starts.forEach((start, i) => {
      if (start >= hi || start + DAY <= lo) return;
      n += Math.min(missed[part][i]!, dueIn(Math.max(lo, start), Math.min(hi, start + DAY)));
    });
    return n;
  };
  /** The latest instant a part's checks can have stayed away from `t` on, from the bars. */
  const away = (part: Part, t: number): number => {
    let reach = t;
    for (let i = Math.floor((t - from) / DAY); i >= 0 && i < DAYS_KEPT; i += 1) {
      const start = starts[i]!;
      reach = Math.min(start + DAY, Math.max(reach, start) + missed[part][i]! * TICK);
      if (reach < start + DAY) break;
    }
    return reach;
  };

  const spans: Span[] = [];
  for (const incident of summary.incidents) {
    const { end, gap } = ending(incident, stale);
    // The list is of the 90 days the bars show: a problem that ended before them is left out.
    if (end !== null && end < from) continue;
    const began = dayKey(incident.s, zone);
    spans.push({
      incident,
      to: end ?? at,
      open: end === null,
      gap,
      home: began < rangeStart ? rangeStart : began,
      here: began >= rangeStart,
      full: problemText(incident, clock, stale, zone, summary.parts[incident.p].s === 'unknown'),
      away: gap && end !== null ? away(incident.p, end) : (end ?? at),
    });
  }

  // The summary is full: the problems it left out are older than every one it holds of their
  // part, so they can hide only in the bars before that one's start, and in the bar it is in.
  const full = summary.incidents.length >= INCIDENTS_MAX;
  const reach = {} as Record<Part, number | null>;
  for (const part of PARTS) reach[part] = null;
  for (const { incident } of spans) {
    const was = reach[incident.p];
    if (was === null || incident.s < was) reach[incident.p] = incident.s;
  }
  /** A bar of trouble no listed problem can account for. */
  const unexplained = (part: Part, i: number): boolean => {
    const cls = cells[part][i];
    if (cls !== 'late' && cls !== 'down') return false;
    const start = starts[i]!;
    const r = reach[part];
    if (full && r !== null && start <= r && r < start + DAY) return true;
    return !spans.some(
      (span) => span.incident.p === part && span.incident.s < start + DAY && span.to > start,
    );
  };

  /** The day as listed, or null for a day with no problem to list. */
  const dayOf = (key: string, date: string, next: string): DayView | null => {
    const begin = keyStart(key, zone);
    const end = keyStart(next, zone);
    const told: Told[] = [];
    for (const span of spans) {
      const { incident } = span;
      const part = copy.parts[incident.p].name;
      const kind = incident.k === 'down' ? copy.problem.down : copy.problem.late;
      if (!(incident.s < end && span.to > begin)) {
        // The checks stopped on a problem before this day and can have stayed away into it:
        // what they last found is said, never that the day had no problems.
        if (span.gap && span.to <= begin && span.away > begin) {
          told.push({
            span,
            whole: false,
            view: {
              kind: incident.k,
              what: fill(copy.problem.stopped, { part, kind, time: zoned(local(span.to, zone)) }),
              when: copy.problem.stoppedWhen,
            },
          });
        }
        continue;
      }
      if (span.open && key === today) told.push({ span, whole: false, view: span.full });
      else if (key === span.home && span.open && span.here) {
        const time = local(incident.s, zone);
        told.push({
          span,
          whole: false,
          view: {
            kind: incident.k,
            what: fill(copy.problem.began, {
              part,
              kind,
              time: `${time.time}${NB}${time.zone}`,
            }),
            when: copy.problem.going,
          },
        });
      } else if (key === span.home) {
        told.push({ span, whole: span.here && !span.open && !span.gap, view: span.full });
      } else {
        let when: string = copy.problem.allDay;
        if (!span.open && span.to <= end) {
          const to = local(span.to, zone);
          when = fill(span.gap ? copy.problem.untilGap : copy.problem.until, {
            time: `${to.time}${NB}${to.zone}`,
          });
        }
        told.push({
          span,
          whole: false,
          view: { kind: incident.k, what: fill(copy.problem.still, { part, kind }), when },
        });
      }
    }
    // A part's problems of one kind that began and ended on this day are one line from
    // `RUN_TOLD_AS_ONE` of them on: how many, their time in all, and from the first to the last.
    const runs = new Map<string, Span[]>();
    for (const line of told) {
      if (!line.whole) continue;
      const name = `${line.span.incident.p} ${line.span.incident.k}`;
      runs.set(name, [...(runs.get(name) ?? []), line.span]);
    }
    const problems: ProblemView[] = [];
    const joined = new Set<string>();
    for (const line of told) {
      const name = `${line.span.incident.p} ${line.span.incident.k}`;
      const run = runs.get(name) ?? [];
      if (!line.whole || run.length < RUN_TOLD_AS_ONE) {
        problems.push(line.view);
        continue;
      }
      if (joined.has(name)) continue;
      joined.add(name);
      const { incident } = line.span;
      problems.push({
        kind: incident.k,
        what: fill(copy.problem.closedMany, {
          part: copy.parts[incident.p].name,
          kind: incident.k === 'down' ? copy.problem.down : copy.problem.late,
          n: run.length,
          dur: dur(run.reduce((sum, span) => sum + span.to - span.incident.s, 0)),
        }),
        when: between(
          Math.min(...run.map((span) => span.incident.s)),
          Math.max(...run.map((span) => span.to)),
          zone,
        ),
      });
    }
    // The bars of the UTC days this day touches, of the days the checks were due on.
    const touched: number[] = [];
    starts.forEach((start, i) => {
      if (start < end && start + DAY > begin) touched.push(i);
    });
    const missing = PARTS.some((part) => touched.some((i) => unexplained(part, i)));
    // Any part with more of the day's checks unanswered than the allowance: not checked in full.
    const short = PARTS.some((part) => unanswered(part, begin, end) > UNANSWERED_ALLOWED);
    if (problems.length > 0) {
      // A day with problems says so too, unless a line of the checks stopping already does.
      const stopped = problems.some((line) => line.when === copy.problem.stoppedWhen);
      // The day of the last check, once the checks are late, was not checked in full either.
      const gap = (short || (stale && key === lastDay)) && !stopped;
      let note: string | null = gap ? copy.problem.stoppedWhen : null;
      if (missing) note = gap ? copy.problem.unlistedGap : copy.problem.unlisted;
      return { date, problems, none: null, note };
    }
    const due = PARTS.flatMap((part) =>
      touched
        .map((i) => cells[part][i]!)
        .filter((cls) => cls !== 'before' && cls !== 'yet' && cls !== 'wait'),
    );
    // A day with no problem listed is left out, but a gap is never let look like a quiet day:
    // a day not checked in full is listed with its note.
    let none: string | null = null;
    // A day after the last check is a gap only once the checks are late; before, its first
    // checks are not due yet.
    if (key > lastDay) none = stale ? copy.problem.unchecked : null;
    else if (due.length === 0) none = copy.problem.unchecked;
    else if (missing) none = short ? copy.problem.unlistedGap : copy.problem.unlisted;
    else if (due.every((cls) => cls === 'none')) none = copy.problem.unchecked;
    // The clock's day, while a part cannot be checked now, says that before any gap of the day.
    else if (key === today && unknownNow && !stale) none = copy.problem.noneUnknown;
    else if (short || (stale && key === lastDay)) none = copy.problem.noneGap;
    return none === null ? null : { date, problems, none, note: null };
  };

  const days: DayView[] = [];
  const older: DayView[] = [];
  let next = dayBefore(today, -1).key;
  let shownFrom = today;
  for (let back = 0; ; back += 1) {
    const { key, date } = dayBefore(today, back);
    if (key < rangeStart) break;
    const listed = back < DAYS_LISTED && key >= firstDay;
    if (listed) shownFrom = key;
    const day = dayOf(key, date, next);
    if (day !== null) (listed ? days : older).push(day);
    next = key;
  }
  // The button counts the problems behind it, and each day there not checked in full.
  const n =
    spans.filter((span) => span.home < shownFrom).length +
    older.filter((day) => day.problems.length === 0).length;
  let button: string | null = null;
  if (n > 0) {
    if (input.expanded) button = copy.problem.hideOlder;
    else button = n === 1 ? copy.problem.showOlderOne : fill(copy.problem.showOlder, { n });
  }
  let began: string | null = null;
  if (summary.first >= from) {
    began = fill(copy.problem.checksBegan, {
      start: zoned(local(summary.first, zone)),
    });
  }
  return {
    days,
    empty: null,
    older,
    button,
    expanded: input.expanded,
    began,
    cut: full ? fill(copy.problem.cut, { n: INCIDENTS_MAX }) : null,
  };
}

/** From the summary and a clock to what the page says. Pure: no DOM, no fetch, no timer. */

import { barOf, dayStart, expected, shareOf } from '../../shared/history.ts';
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
/** The problems list shows this many until "Show all". */
export const SLOTS = 3;

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
  cls: BarClass | 'wait';
  /** The bar's name; null while there is nothing to name. */
  label: string | null;
  picked: boolean;
}

export interface View {
  banner: { shape: Shape; lead: string[]; more: string | null };
  parts: {
    part: Part;
    name: string;
    says: string;
    shape: Shape;
    word: string;
    /** A file part has an "Updated" line (empty until its stamp is read); the others have none. */
    file: boolean;
    updated: string | null;
  }[];
  history: { part: Part; name: string; share: string; bars: BarView[]; note: string }[];
  problems: {
    /** `SLOTS` at least; null: an empty slot. */
    slots: ({ what: string; when: string } | null)[];
    /** Said when there is no problem to list. */
    empty: string | null;
    button: string | null;
    expanded: boolean;
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
  const d = count(Math.floor(hours / 24), copy.dur.day, copy.dur.days);
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

const UTC_DAY = new Intl.DateTimeFormat('en-US', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

/** 'Tue, Nov 3': a bar's UTC day. */
function utcDay(t: number): string {
  const parts = new Map(UTC_DAY.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  return `${parts.get('weekday')}, ${parts.get('month')} ${parts.get('day')}`;
}

interface Local {
  date: string;
  time: string;
  zone: string;
}

/** An instant in the reader's zone: 'Nov 7', '6:10 AM', 'EST'. */
function local(t: number, zone: string | undefined): Local {
  const format = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
    timeZone: zone,
  });
  const parts = new Map(format.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  return {
    date: `${parts.get('month')} ${parts.get('day')}`,
    time: `${parts.get('hour')}:${parts.get('minute')} ${parts.get('dayPeriod')}`,
    zone: parts.get('timeZoneName') ?? '',
  };
}

function dayText(
  t: number,
  counts: readonly [number, number, number],
  e: number,
  today: boolean,
): string {
  const date = utcDay(t);
  const bar = barOf(counts, e);
  if (bar.e === 0) return fill(copy.day.before, { date });
  if (bar.k === 0) return fill(copy.day.none, { date });
  const [, late, down] = counts;
  const missing = dur(bar.m * TICK);
  if (late === 0 && down === 0) {
    if (bar.m > 0) return fill(copy.day.okGap, { date, dur: missing });
    return fill(today ? copy.day.today : copy.day.ok, { date });
  }
  const list: string[] = [];
  if (down > 0) list.push(fill(copy.day.down, { dur: dur(down * TICK) }));
  if (late > 0) list.push(fill(copy.day.late, { dur: dur(late * TICK) }));
  if (bar.m > 0) list.push(fill(copy.day.gap, { dur: missing }));
  return fill(copy.day.mixed, {
    date,
    list: list.reduce((a, b) => fill(copy.list.comma, { a, b })),
  });
}

function problemText(
  incident: SummaryIncident,
  clock: number,
  stale: boolean,
  zone: string | undefined,
): { what: string; when: string } {
  const part = copy.parts[incident.p].name;
  const kind = incident.k === 'down' ? copy.problem.down : copy.problem.late;
  const from = local(incident.s, zone);
  const start = `${from.date}, ${from.time}`;
  let end = incident.e;
  let gap = incident.g === 1;
  if (end === null && stale) {
    // No fresh readings: it is drawn as one whose readings stopped, a tick after its last.
    end = (incident.l ?? incident.s) + TICK;
    gap = true;
  }
  if (end === null) {
    return {
      what: fill(copy.problem.open, { part, kind, start: `${start} ${from.zone}` }),
      when: fill(copy.problem.openWhen, { dur: dur(clock - incident.s) }),
    };
  }
  if (gap) {
    return {
      what: fill(copy.problem.gap, { part, kind, dur: dur(end - incident.s) }),
      when: fill(copy.problem.gapWhen, { start: `${start} ${from.zone}` }),
    };
  }
  const to = local(end, zone);
  return {
    what: fill(copy.problem.closed, { part, kind, dur: dur(end - incident.s) }),
    when: fill(copy.problem.closedWhen, {
      // Both zones are named when the clocks changed in between.
      start: to.zone === from.zone ? start : `${start} ${from.zone}`,
      end: `${to.date === from.date ? '' : `${to.date}, `}${to.time} ${to.zone}`,
    }),
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
  const bars: BarView[] = Array.from({ length: DAYS_KEPT }, () => ({
    cls: 'wait',
    label: null,
    picked: false,
  }));
  return {
    banner: { shape, lead: [lead], more },
    parts: PARTS.map((part) => ({
      part,
      name: copy.parts[part].name,
      says: copy.parts[part].says,
      shape,
      word: copy.state[shape],
      file: FILES.includes(part),
      updated: null,
    })),
    history: PARTS.map((part) => ({
      part,
      name: copy.parts[part].name,
      share: first ? copy.share.none : '',
      bars,
      note: '',
    })),
    problems: {
      slots: Array.from({ length: SLOTS }, () => null),
      empty: null,
      button: null,
      expanded: false,
    },
  };
}

/** What the page says for an input. */
export function viewOf(input: Input): View {
  if (input.kind !== 'data' || input.summary === null) return waiting(input);
  const { summary, clock, zone } = input;
  const stale = clock - summary.now > STALE_AFTER;
  const sinceCheck = ago(clock - summary.now);

  const names = (state: State): string[] =>
    PARTS.filter((part) => summary.parts[part].s === state).map((part) => copy.parts[part].name);
  const down = names('down');
  const late = names('late');
  let shape: Shape;
  let lead: string[];
  let more: string;
  if (stale) {
    shape = 'unknown';
    lead = [copy.banner.stale];
    more = fill(copy.banner.staleMore, { ago: sinceCheck });
  } else {
    if (down.length > 0) {
      shape = 'down';
      lead = [fill(copy.banner.down, { parts: listed(down) })];
      if (late.length > 0) lead.push(fill(copy.banner.late, { parts: listed(late) }));
    } else if (late.length > 0) {
      shape = 'late';
      lead = [fill(copy.banner.late, { parts: listed(late) })];
    } else if (names('unknown').length > 0) {
      shape = 'unknown';
      lead = [copy.banner.unknown];
    } else {
      shape = 'ok';
      lead = [copy.banner.ok];
    }
    more = fill(input.kept ? copy.banner.kept : copy.banner.checked, { ago: sinceCheck });
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
      updated: made === undefined ? null : fill(copy.updated, { ago: ago(clock - made) }),
    };
  });

  const from = dayStart(summary.from);
  const history = PARTS.map((part) => {
    const counts = summary.days[part];
    const expectedByDay = counts.map((_, i) =>
      expected(from + i * DAY, summary.first, summary.now),
    );
    const bars = counts.map((triple, i): BarView => {
      const e = expectedByDay[i] ?? 0;
      return {
        cls: barOf(triple, e).cls,
        label: dayText(from + i * DAY, triple, e, i === counts.length - 1),
        picked: input.picked !== null && input.picked.part === part && input.picked.day === i,
      };
    });
    const share = shareOf(counts, expectedByDay);
    const days = count(share.days, copy.dur.day, copy.dur.days);
    return {
      part,
      name: copy.parts[part].name,
      share: share.pct === null ? copy.share.none : fill(copy.share.line, { pct: share.pct, days }),
      bars,
      note: bars.find((bar) => bar.picked)?.label ?? '',
    };
  });

  const all = summary.incidents.map((incident) => problemText(incident, clock, stale, zone));
  const shown: View['problems']['slots'] = input.expanded ? [...all] : all.slice(0, SLOTS);
  while (shown.length < SLOTS) shown.push(null);
  let empty: string | null = null;
  if (all.length === 0) {
    const young = clock - summary.first < DAYS_KEPT * DAY;
    empty = young
      ? fill(copy.problem.noneSince, { date: local(summary.first, zone).date })
      : copy.problem.none;
  }
  let button: string | null = null;
  if (all.length > SLOTS) {
    button = input.expanded
      ? copy.problem.showFewer
      : fill(copy.problem.showAll, { n: all.length });
  }
  return {
    banner: { shape, lead, more },
    parts,
    history,
    problems: { slots: shown, empty, button, expanded: input.expanded },
  };
}

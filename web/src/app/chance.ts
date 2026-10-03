/**
 * The school panel's chance section, as the panel shows it (ui/ChanceSection.svelte):
 *
 * 1. the chance of no school as the headline, for the first day that is not
 *    decided or under way in the school's own time zone, what moved it since
 *    the run before, and the chance of a delayed start instead;
 * 2. the early signals: weather that already happened, and the districts next
 *    door that already posted a status for that day (live/closings.json rows,
 *    mapped to districts through the directory), each with its time, and when
 *    this district usually announces, with a live countdown, all in time order;
 * 3. the night hour by hour, drawn to scale, a bar an hour (or two or three,
 *    so every bar stays a readable width), its marks and their key (the
 *    chart's numbers are worked out here, so they are tested);
 * 4. how the chance adds up: the base, then each reason's points, each in a
 *    short sentence, the district's record in the sentence it proves. It
 *    shows only when every part can be said and the parts add up to the
 *    headline exactly; a sum that does not is never shown.
 *
 * Every time is the school's wall clock, in its district's time zone, with
 * the zone's short name where the viewer's differs (copy-chance.ts Zones).
 * Every word comes from src/copy.ts and src/copy-chance.ts. A part the files
 * do not give is left out, and nothing is filled in.
 */

import { STATUS_KEYS, format } from '../copy';
import type { StatusKey } from '../copy';
import { chanceCopy, chanceFormat, localHour } from '../copy-chance';
import type { BaseInput, ReasonInput, RecordCount, Zones } from '../copy-chance';
import { decodeDay } from '../data/closings';
import { NO_DETAIL } from '../data/forecast-detail';
import type {
  EventDetail,
  ForecastDetail,
  HoursDetail,
  ReasonDetail,
  RecordDetail,
} from '../data/forecast-detail';
import type { DayOutlook, Outlook } from '../data/school-day';
import { parseInstant } from '../state/instant';
import type { ClosingsFile, DirectoryStamp, LocalDate } from '../types/generated';

const HOUR_MS = 3_600_000;
const MINUTE_MS = 60_000;
/** At most this many districts next door on the timeline, the first to post first. */
export const MAX_NEIGHBOR_MOMENTS = 4;
/** Without its bus time, a day is under way from this hour, the school's own clock. */
export const UNDER_WAY_HOUR = 9;
/** The usual announcement stays on the timeline this long after its time. */
const ANNOUNCE_GRACE_MS = 3 * HOUR_MS;

/** A status line, as the panel's status block shows it (app/school.ts StatusLineView). */
export interface StatusLine {
  readonly tone: StatusKey | 'open';
  readonly headline: string;
  readonly detail: string | null;
  readonly note: string | null;
}

/** District names and which district each school is in, from the directory. */
export interface Names {
  /** The directory these positions are in: a closings file for another is not read with it. */
  readonly stamp: DirectoryStamp;
  /** A school's district position, or -1. */
  districtOf(school: number): number;
  /** A district's short name ("Blue Valley"), or null. */
  name(district: number): string | null;
}

export interface MovedView {
  readonly direction: 'up' | 'down' | 'same';
  readonly text: string;
}

/** One moment on the timeline. */
export interface MomentView {
  readonly key: string;
  /** "8:41 PM", "8:41 PM CT". */
  readonly time: string;
  readonly text: string;
  /** A status a district posted (its map dot), what already happened, or what comes next. */
  readonly mark: StatusKey | 'event' | 'next';
  /** For what comes next: when, for its live countdown; null otherwise. */
  readonly at: Date | null;
}

/** One bar, in pixels above the plot's foot. */
export interface BarView {
  readonly bottom: number;
  readonly height: number;
  readonly lit: boolean;
  /** A value below 0, hanging from the zero rule. */
  readonly below: boolean;
}

/** A time along the chart's foot, under the bar at `at`: "11 PM", or "Now" under this hour. */
export interface TimeView {
  readonly at: number;
  readonly label: string;
  /** The last, the bus hour's: set to end where the plot ends, so it never runs past it. */
  readonly end: boolean;
}

/** One row of the chart's key: its mark, drawn small, and what the mark is. */
export type KeyRowView =
  | { readonly mark: 'announces' | 'heavy'; readonly text: string }
  | {
      readonly mark: 'buses';
      /** The value at the bus hour, said first: "6 to 9 in". */
      readonly value: string;
      /** " when buses run at 7 AM". */
      readonly rest: string;
      /** How the bus hour is drawn: its range, else its lit bar, else its line. */
      readonly glyph: 'range' | 'bar' | 'line';
    };

export interface ChartView {
  readonly kind: 'snow_total' | 'wind_chill';
  readonly title: string;
  /** The chart in a sentence, for a screen reader. */
  readonly summary: string;
  /** The plot's height in pixels. */
  readonly plot: number;
  /** The zero rule, in pixels above the plot's foot. */
  readonly zero: number;
  /** Hours a bar stands for: 1, or 2 or 3 on a long night. */
  readonly step: number;
  readonly bars: readonly BarView[];
  readonly times: readonly TimeView[];
  /** The usual announcement's dashed line, in bars from the first bar's left edge; or null. */
  readonly announces: number | null;
  /** Where the bus hour's dashed line stops, in pixels above the plot's foot. */
  readonly busTop: number;
  /** The bus hour's low-to-high range, on the last bar; null without one. */
  readonly range: { readonly bottom: number; readonly height: number } | null;
  /** The key under the chart, a row a mark, in time order, the bus hour's last. */
  readonly key: readonly KeyRowView[];
}

export interface WhyLineView {
  readonly key: string;
  /** "+16", "−3". */
  readonly points: string;
  /** "Blue Valley and Olathe, next door, canceled." */
  readonly text: string;
}

export interface WhyView {
  /** "How we got 64%". */
  readonly title: string;
  /** Where the sum starts: "30", and the district's own rate in a sentence. */
  readonly base: { readonly number: string; readonly text: string };
  readonly lines: readonly WhyLineView[];
}

export interface ChanceView {
  /** The school's status lines, decided first: "Closed today". */
  readonly status: readonly StatusLine[];
  /** The day the chance is for. */
  readonly day: LocalDate;
  /** "64", "<1". */
  readonly number: string;
  /** "Chance of no school Tuesday". */
  readonly meaning: string;
  readonly moved: MovedView | null;
  readonly moments: readonly MomentView[];
  readonly chart: ChartView | null;
  readonly why: WhyView | null;
  /** "18% chance of a delayed start instead", or null. */
  readonly delay: string | null;
  /**
   * The live countdown to a moment, as the clock reads `now`: "in 8h 25m",
   * or null once it has come. Here, so the panel's own code carries none of
   * the chance section's words.
   */
  readonly countdown: (at: Date, now: Date) => string | null;
}

export interface ChanceInput {
  readonly outlook: Outlook;
  /** Each day's status is decided (closed, delayed, remote, dismissing early): no chance for it. */
  readonly decided: { readonly today: boolean; readonly tomorrow: boolean };
  readonly status: readonly StatusLine[];
  /** The school's district, by its short name ("Shawnee Mission"). */
  readonly district: string;
  readonly closings: ClosingsFile | null;
  /** The directory's names, once read; null before (the neighbors wait for it). */
  readonly names: Names | null;
  readonly now: Date;
  /** The viewer's time zone: the school's zone is named after a time where they differ. */
  readonly timeZone: string;
}

type Forecast = Extract<DayOutlook, { state: 'forecast' }>;

// Names ---------------------------------------------------------------------------------

/** Words a district's name ends with that only say it is a district. */
const DISTRICT_WORDS =
  /\s+(?:(?:unified|independent|consolidated|community|area|public|local|exempted village|joint)\s+)*(?:school\s+district|schools?|school\s+corporation|district|usd|isd|cisd|sd)(?:\s+(?:no\.?\s*)?\d+[a-z]?)?$/i;
/** What is left of a name that was all such words. */
const GENERIC = /^(?:unified|independent|consolidated|community|area|public|local|joint)$/i;

/**
 * A district's name, short, as a family says it: "Shawnee Mission" for Shawnee
 * Mission Public Schools, "Lee County" for Lee County Schools. A name that is
 * all such words, or would be cut to less than 3 letters, stays whole.
 */
export function shortDistrictName(shown: string): string {
  const short = shown.replace(DISTRICT_WORDS, '').trim();
  return short.length >= 3 && !GENERIC.test(short) ? short : shown;
}

// The headline ----------------------------------------------------------------------------

/** The wall clock of an instant in a time zone, as milliseconds of that day and time in UTC. */
function wallClock(instant: Date, timeZone: string): number {
  const parts = format.dateTimeFormat('clock', timeZone).formatToParts(instant);
  const minutes = localHour(instant, timeZone) * 60 + Number(format.part(parts, 'minute'));
  return Date.parse(`${format.localDay(instant, timeZone)}T00:00:00Z`) + minutes * MINUTE_MS;
}

/** The instant a calendar day's hour strikes in a time zone: 9 AM on Tuesday in Kansas City. */
export function atLocalHour(day: LocalDate, hour: number, timeZone: string): Date {
  const target = Date.parse(`${day}T00:00:00Z`) + hour * HOUR_MS;
  let at = target;
  // Two steps settle any offset; a third, the rare hour a clock change moves.
  for (let i = 0; i < 3; i++) at += target - wallClock(new Date(at), timeZone);
  return new Date(at);
}

/**
 * Whether a day is under way: once its buses have run (with no closing
 * posted, the children are at school), or without its bus time, from 9 AM on
 * the school's own clock.
 */
function underWay(day: Forecast & { readonly day: LocalDate }, now: Date, timeZone: string) {
  const buses = day.detail?.busesAt ?? null;
  if (buses !== null) return now >= buses;
  try {
    return now >= atLocalHour(day.day, UNDER_WAY_HOUR, timeZone);
  } catch {
    // A clock this browser cannot read: the day is not said.
    return true;
  }
}

/**
 * The day the chance is for: the first of today and tomorrow, in the
 * school's time zone, that is not decided, has a forecast, and is not under way.
 */
export function headlineDay(
  outlook: Outlook,
  decided: ChanceInput['decided'],
  now: Date,
): (Forecast & { readonly day: LocalDate }) | null {
  if (outlook === null) return null;
  const days = [decided.today ? null : outlook.today, decided.tomorrow ? null : outlook.tomorrow];
  for (const day of days) {
    if (day?.state !== 'forecast' || day.day === undefined) continue;
    const dated = day as Forecast & { readonly day: LocalDate };
    if (underWay(dated, now, outlook.timeZone)) continue;
    return dated;
  }
  return null;
}

/** Which way the chance moved since the run before, in whole percent, and in words. */
export function movedView(
  current: number,
  previous: ForecastDetail['previous'],
  now: Date,
  zones: Zones,
): MovedView | null {
  if (previous === null) return null;
  let text: string | null;
  try {
    text = chanceFormat.moved({
      previous: previous.noSchool,
      current,
      at: previous.at,
      now,
      zones,
    });
  } catch {
    return null;
  }
  if (text === null) return null;
  const before = Math.round(previous.noSchool * 100);
  const after = Math.round(current * 100);
  return { direction: before === after ? 'same' : before < after ? 'up' : 'down', text };
}

// The timeline ----------------------------------------------------------------------------

/** One district next door that posted a status for the day: its first post. */
interface Posted {
  readonly district: number;
  readonly status: StatusKey;
  readonly at: Date;
}

/**
 * The districts next door that posted a status for `day`, each once, at its
 * first post with a time, in the order they posted: from the closings rows of
 * that day, through the directory's district of each school.
 */
export function neighborPosts(
  closings: ClosingsFile | null,
  day: LocalDate,
  neighbors: readonly number[],
  names: Names | null,
  now: Date,
): Posted[] {
  if (closings === null || names === null || neighbors.length === 0) return [];
  const { stamp } = names;
  const same =
    closings.directory.generated_on === stamp.generated_on &&
    closings.directory.schools === stamp.schools &&
    closings.directory.districts === stamp.districts;
  const group = closings.days.find((item) => item.day === day);
  const generated = parseInstant(closings.generated_at);
  if (!same || group === undefined || generated === null) return [];
  const wanted = new Set(neighbors);
  const rows = decodeDay(group);
  const first = new Map<number, Posted>();
  const minute = Math.floor(generated.getTime() / MINUTE_MS);
  rows.schools.forEach((school, i) => {
    const ago = group.announced[i] ?? null;
    const code = rows.statuses[i];
    if (ago === null || code === undefined) return;
    const district = names.districtOf(school);
    if (!wanted.has(district)) return;
    const at = new Date((minute - ago) * MINUTE_MS);
    const status = STATUS_KEYS[code];
    if (status === undefined || at > now) return;
    const seen = first.get(district);
    if (seen === undefined || at < seen.at) first.set(district, { district, status, at });
  });
  return [...first.values()]
    .sort((a, b) => a.at.getTime() - b.at.getTime() || a.district - b.district)
    .slice(0, MAX_NEIGHBOR_MOMENTS);
}

/**
 * The timeline, in time order: what happened, who posted, and when this
 * district usually announces, which counts down while it is still to come
 * and takes its place among what happened once it has passed.
 */
export function momentsOf(
  detail: ForecastDetail,
  posts: readonly Posted[],
  names: Names | null,
  input: {
    readonly day: LocalDate;
    readonly district: string;
    readonly now: Date;
    readonly zones: Zones;
  },
): MomentView[] {
  const { day, district, now, zones } = input;
  const moments: { at: Date; moment: MomentView }[] = [];
  const events: readonly EventDetail[] = detail.events;
  for (const event of events) {
    if (event.at > now) continue;
    moments.push({
      at: event.at,
      moment: {
        key: `event ${event.kind} ${String(event.at.getTime())}`,
        time: chanceFormat.momentTime(event.at, now, zones),
        text: chanceFormat.weatherEvent(
          event.kind,
          event.kind === 'snow_stopped' ? event.inches : null,
        ),
        mark: 'event',
        at: null,
      },
    });
  }
  for (const post of posts) {
    const name = names?.name(post.district) ?? null;
    if (name === null) continue;
    moments.push({
      at: post.at,
      moment: {
        key: `district ${String(post.district)}`,
        time: chanceFormat.momentTime(post.at, now, zones),
        text: chanceFormat.neighborPosted(name, post.status, day),
        mark: post.status,
        at: null,
      },
    });
  }
  const at = detail.announcesAt;
  if (at !== null && now.getTime() - at.getTime() <= ANNOUNCE_GRACE_MS) {
    const ahead = at > now;
    moments.push({
      at,
      moment: {
        key: 'announces',
        time: chanceFormat.momentTime(at, now, zones),
        text: chanceFormat.usuallyAnnounces(district),
        mark: ahead ? 'next' : 'event',
        at: ahead ? at : null,
      },
    });
  }
  return moments.sort((a, b) => a.at.getTime() - b.at.getTime()).map((item) => item.moment);
}

// The chart -------------------------------------------------------------------------------

/** Pixels between two steps of the scale. */
export const TICK_PX = 40;
/**
 * At most this many bars: past it, a bar stands for 2 or 3 hours, so each is
 * 16 px wide or more on the narrowest plot, its bar 60% of that.
 */
export const MAX_BARS = 18;
/**
 * The narrowest plot: the panel's width on a 320 px phone, less its 16 px
 * gutters. A time's words at the chart's foot are at most TIME_LABEL_PX wide
 * (13 px Geist, "12 AM"), with TIME_GAP_PX between two of them.
 */
export const NARROWEST_PLOT_PX = 288;
const TIME_LABEL_PX = 40;
const TIME_GAP_PX = 8;
const SNOW_STEPS = [0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50];
const COLD_STEPS = [5, 10, 20, 25, 40, 50];

export interface Scale {
  readonly min: number;
  readonly max: number;
  readonly step: number;
  /** The steps' values, from the foot up. */
  readonly ticks: readonly number[];
}

/**
 * The chart's scale: 2 or 3 steps of a round size from 0 up to the most snow
 * (the range's high end included), or around 0 for how cold it feels.
 */
export function chartScale(
  kind: HoursDetail['kind'],
  values: readonly number[],
  high: number | null,
): Scale {
  if (kind === 'snow_total') {
    const top = Math.max(0, high ?? 0, ...values);
    const step = SNOW_STEPS.find((size) => Math.ceil(top / size) <= 3) ?? 60;
    const steps = Math.max(2, Math.ceil(top / step));
    return {
      min: 0,
      max: step * steps,
      step,
      ticks: Array.from({ length: steps + 1 }, (_, i) => i * step),
    };
  }
  const low = Math.min(0, ...values);
  const top = Math.max(0, ...values);
  const count = (size: number): number => Math.ceil(top / size) + Math.ceil(-low / size);
  const step = COLD_STEPS.find((size) => count(size) <= 3) ?? 100;
  let above = Math.ceil(top / step);
  let below = Math.ceil(-low / step);
  // At least two steps, the second on the side the values are.
  if (above + below < 2) {
    if (top > 0) above = 2 - below;
    else below = 2 - above;
  }
  return {
    min: -below * step,
    max: above * step,
    step,
    ticks: Array.from({ length: above + below + 1 }, (_, i) => (i - below) * step),
  };
}

/** Hours a bar stands for, so no more than MAX_BARS bars draw `hours` hours. */
export function hoursPerBar(hours: number): number {
  return Math.max(1, Math.ceil(hours / MAX_BARS));
}

/**
 * The times at the chart's foot, by bar: the first ("Now", when it is this
 * hour) and the last (the buses) always; then where the heaviest snow starts
 * and ends, when the snow starts, and every third hour (or sixth, or ninth, a
 * bar standing for more), each only where its words keep clear of those placed
 * on the narrowest plot. Each starts at its bar's left edge; the last ends
 * where the plot does.
 */
export function chartTimes(input: {
  readonly instants: readonly Date[];
  readonly step: number;
  readonly heavy: { readonly first: number; readonly last: number } | null;
  readonly snowStarts: number;
  readonly isNow: boolean;
  readonly timeZone: string;
}): TimeView[] {
  const { instants, step, heavy, snowStarts, isNow, timeZone } = input;
  const count = instants.length;
  const last = count - 1;
  const slot = NARROWEST_PLOT_PX / count;
  const box = (at: number): [number, number] =>
    at === last
      ? [NARROWEST_PLOT_PX - TIME_LABEL_PX, NARROWEST_PLOT_PX]
      : [at * slot, at * slot + TIME_LABEL_PX];
  const wanted: number[] = [0, last];
  if (heavy !== null) wanted.push(heavy.first - 1, heavy.last);
  if (snowStarts > 0) wanted.push(snowStarts);
  instants.forEach((instant, at) => {
    if (at > 0 && at < last && localHour(instant, timeZone) % (3 * step) === 0) wanted.push(at);
  });
  const placed: number[] = [];
  for (const at of wanted) {
    if (at < 0 || at >= count || placed.includes(at)) continue;
    const [left, right] = box(at);
    const clear = placed.every((other) => {
      const [l, r] = box(other);
      return right + TIME_GAP_PX <= l || r + TIME_GAP_PX <= left;
    });
    if (clear) placed.push(at);
  }
  return placed
    .sort((a, b) => a - b)
    .map((at) => ({
      at,
      label:
        at === 0 && isNow
          ? chanceCopy.now
          : chanceFormat.shortTime(instants[at] ?? new Date(NaN), timeZone),
      end: at === last,
    }));
}

/**
 * The night hour by hour, from this hour to the bus hour: bars on a scale (a
 * bar an hour, or one for every 2 or 3 on a long night, back from the bus
 * hour), the lit hours, the times at its foot, the usual announcement's
 * dashed line and the bus hour's, with its range, and the key to them. Null
 * when there is no series, or fewer than two of its hours are still to come.
 */
export function chartView(detail: ForecastDetail, now: Date, zones: Zones): ChartView | null {
  const { hours, busesAt, announcesAt } = detail;
  if (hours === null || busesAt === null) return null;
  const zone = zones.school;
  // From this hour on: the hours gone by are not the night ahead.
  const gone = Math.max(0, Math.floor((now.getTime() - hours.start.getTime()) / HOUR_MS));
  const series = hours.values.slice(gone);
  if (series.length < 2) return null;
  const start = new Date(hours.start.getTime() + gone * HOUR_MS);
  const step = hoursPerBar(series.length);
  const count = Math.floor((series.length - 1) / step) + 1;
  /** The series' hour bar `at` draws: every step-th, back from the bus hour. */
  const hourOf = (at: number): number => series.length - 1 - (count - 1 - at) * step;
  const values = Array.from({ length: count }, (_, at) => series[hourOf(at)] ?? 0);
  const last = values.at(-1) ?? 0;
  const scale = chartScale(hours.kind, series, hours.range?.high ?? null);
  const plot = TICK_PX * (scale.ticks.length - 1);
  const y = (value: number): number =>
    ((Math.min(scale.max, Math.max(scale.min, value)) - scale.min) / (scale.max - scale.min)) *
    plot;
  const zero = y(0);
  const heavy =
    hours.heavy === null || hours.heavy.last - gone < 0
      ? null
      : { first: Math.max(0, hours.heavy.first - gone), last: hours.heavy.last - gone };
  const snow = hours.kind === 'snow_total';
  // A bar is lit where the heaviest snow falls in the hours it stands for.
  const lit = (at: number): boolean => {
    if (!snow) return at === count - 1;
    if (heavy === null) return false;
    const from = at === 0 ? 0 : hourOf(at - 1) + 1;
    return Math.max(from, heavy.first) <= Math.min(hourOf(at), heavy.last);
  };
  // Each bar exactly its value: a trace is a sliver, no snow is no bar.
  const bars = values.map((value, at): BarView => {
    const end = y(value);
    return {
      bottom: Math.min(zero, end),
      height: Math.abs(end - zero),
      lit: lit(at),
      below: value < 0,
    };
  });
  const litBars = bars.map((bar, at) => (bar.lit ? at : -1)).filter((at) => at >= 0);
  const instants = values.map((_, at) => new Date(start.getTime() + hourOf(at) * HOUR_MS));
  const firstSnow = snow ? values.findIndex((value) => value > 0) : -1;
  const times = chartTimes({
    instants,
    step,
    heavy:
      snow && litBars.length > 0 ? { first: litBars[0] ?? 0, last: litBars.at(-1) ?? 0 } : null,
    snowStarts: firstSnow,
    isNow: hourOf(0) === 0 && now >= start && now.getTime() < start.getTime() + HOUR_MS,
    timeZone: zone,
  });
  // The announcement's line, where it falls within the night drawn.
  let announces: number | null = null;
  if (announcesAt !== null) {
    const bar = ((announcesAt.getTime() - start.getTime()) / HOUR_MS - hourOf(0)) / step;
    if (bar >= 0 && bar <= count - 1) announces = bar;
  }
  const key: { at: number; row: KeyRowView }[] = [];
  if (snow && hours.heavy !== null && litBars.length > 0) {
    const from = new Date(hours.start.getTime() + (hours.heavy.first - 1) * HOUR_MS);
    const to = new Date(hours.start.getTime() + hours.heavy.last * HOUR_MS);
    key.push({
      at: from.getTime(),
      row: { mark: 'heavy', text: chanceFormat.heaviestKey(from, to, zones) },
    });
  }
  if (announcesAt !== null && announces !== null) {
    key.push({
      at: announcesAt.getTime(),
      row: { mark: 'announces', text: chanceFormat.announcesKey(announcesAt, zones) },
    });
  }
  key.sort((a, b) => a.at - b.at);
  const value =
    hours.range !== null
      ? chanceFormat.inches(hours.range.low, hours.range.high)
      : snow
        ? chanceFormat.inches(last)
        : chanceFormat.degrees(last);
  const answer = chanceFormat.busesKey(value, busesAt, zones);
  const evening = localHour(start, zone) >= 17;
  return {
    kind: hours.kind,
    title: snow ? chanceCopy.snowTitle : evening ? chanceCopy.coldTonight : chanceCopy.coldTitle,
    summary: chanceFormat.chartSummary(
      hours.kind,
      busesAt,
      hours.range?.low ?? last,
      hours.range?.high ?? last,
      zones,
    ),
    plot,
    zero,
    step,
    bars,
    times,
    announces,
    busTop: hours.range !== null ? y(hours.range.high) : Math.max(y(last), zero),
    range:
      hours.range === null
        ? null
        : { bottom: y(hours.range.low), height: y(hours.range.high) - y(hours.range.low) },
    key: [
      ...key.map((item) => item.row),
      {
        mark: 'buses',
        ...answer,
        glyph: hours.range !== null ? 'range' : bars.at(-1)?.lit === true ? 'bar' : 'line',
      },
    ],
  };
}

// How the chance adds up ------------------------------------------------------------------

/** The record's count, for the sentence that cites it; null when it is not a record of storms. */
export function recordCount(record: RecordDetail | null): RecordCount | null {
  const inches = record?.inches ?? null;
  if (record === null || inches === null) return null;
  const closed = record.days.filter((past) => past.status === 0 || past.status === 2).length;
  const remote = record.days.filter((past) => past.status === 2).length;
  return { closed, remote, days: record.days.length, inches };
}

/** A reason as copy.ts words it: its numbers, and what its sentence needs from the rest. */
function reasonInput(
  reason: ReasonDetail,
  detail: ForecastDetail,
  day: LocalDate,
  names: Names | null,
): ReasonInput | null {
  switch (reason.kind) {
    case 'snow_total':
      return {
        ...reason,
        record: detail.record?.proves === 'snow_total' ? recordCount(detail.record) : null,
      };
    case 'record': {
      const count = detail.record?.proves === 'record' ? recordCount(detail.record) : null;
      return count === null ? null : { kind: 'record', points: reason.points, record: count };
    }
    case 'neighbors': {
      const found = reason.districts.map((district) => names?.name(district) ?? null);
      const status = STATUS_KEYS[reason.status];
      if (status === undefined) return null;
      return {
        kind: 'neighbors',
        points: reason.points,
        names: found.every((name): name is string => name !== null) ? found : null,
        count: reason.districts.length,
        status,
      };
    }
    case 'timing':
      return { ...reason, buses: detail.busesAt };
    case 'cold':
    case 'sun':
      return { ...reason, day };
    case 'snow_stops':
      return { ...reason, buses: detail.busesAt, day };
    case 'wind_chill':
    case 'icy_roads':
    case 'ice':
      return reason;
  }
}

/**
 * How the chance adds up, or null. Null unless the base and every reason's
 * points add up to the headline exactly and every reason can be said. The
 * file never gives a certainty (0.01 to 0.99), so the sum always has whole
 * points to show, 1% and 99% too.
 */
export function whyView(input: {
  readonly detail: ForecastDetail;
  readonly chance: number;
  readonly day: LocalDate;
  readonly district: string;
  readonly names: Names | null;
  readonly now: Date;
  readonly zones: Zones;
}): WhyView | null {
  const { detail, chance, day, district, names, now, zones } = input;
  const why = detail.why;
  const percent = Math.round(chance * 100);
  if (why === null || percent < 1 || percent > 99) return null;
  const parts = [why.base.points, ...why.reasons.map((reason) => reason.points)];
  if (!parts.every((part) => Number.isInteger(part))) return null;
  if (parts.reduce((sum, part) => sum + part, 0) !== percent) return null;
  try {
    const base: BaseInput = why.base;
    const lines: WhyLineView[] = [];
    for (const reason of why.reasons) {
      const said = reasonInput(reason, detail, day, names);
      if (said === null) return null;
      lines.push({
        key: reason.kind,
        points: chanceFormat.points(reason.points),
        text: chanceFormat.reason(said, district, now, zones),
      });
    }
    return {
      title: chanceFormat.howWeGot(chance),
      base: { number: String(why.base.points), text: chanceFormat.baseReason(base, district) },
      lines,
    };
  } catch {
    // A number the words refuse: no sum rather than a wrong one.
    return null;
  }
}

// The section -----------------------------------------------------------------------------

/**
 * The chance section, or null when there is no chance to give: no forecast
 * for a day that is not decided or under way. Each part is null (or empty)
 * where the files do not give it; the headline shows whenever the chance
 * itself is known.
 */
export function chanceView(input: ChanceInput): ChanceView | null {
  const { outlook, decided, status, district, closings, names, now, timeZone } = input;
  if (outlook === null) return null;
  const forecast = headlineDay(outlook, decided, now);
  if (forecast === null) return null;
  const { day, noSchool } = forecast;
  const zones: Zones = { school: outlook.timeZone, viewer: timeZone };
  const detail = forecast.detail ?? NO_DETAIL;
  const neighbors = outlook.neighbors ?? [];
  let moments: MomentView[];
  let chart: ChartView | null;
  let number: string;
  let meaning: string;
  try {
    number = chanceFormat.chanceNumber(noSchool);
    meaning = chanceFormat.chanceOn(day);
  } catch {
    return null;
  }
  try {
    moments = momentsOf(detail, neighborPosts(closings, day, neighbors, names, now), names, {
      day,
      district,
      now,
      zones,
    });
  } catch {
    moments = [];
  }
  try {
    chart = chartView(detail, now, zones);
  } catch {
    chart = null;
  }
  const moved = movedView(noSchool, detail.previous, now, zones);
  let delay: string | null = null;
  if (Math.round(forecast.delay * 100) >= 1) {
    try {
      delay = chanceFormat.delayInstead(forecast.delay);
    } catch {
      delay = null;
    }
  }
  return {
    status,
    day,
    number,
    meaning,
    moved,
    moments,
    chart,
    why: whyView({ detail, chance: noSchool, day, district, names, now, zones }),
    delay,
    countdown: (at, clock) => {
      try {
        return chanceFormat.countdown(at, clock, outlook.timeZone);
      } catch {
        return null;
      }
    },
  };
}

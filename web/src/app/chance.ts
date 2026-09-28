/**
 * The school panel's chance section, as the panel shows it (ui/ChanceSection.svelte):
 *
 * 1. the chance of no school as the headline, for the first day that is not
 *    decided, and what moved it since the run before;
 * 2. the early signals: weather that already happened, and the districts next
 *    door that already posted a status for that day (live/closings.json rows,
 *    mapped to districts through the directory), each with its time; then when
 *    this district usually announces, with a live countdown;
 * 3. the night hour by hour, drawn to scale (the chart's numbers and where its
 *    words go are worked out here, so they can be tested);
 * 4. how the chance adds up: the base, then each reason's points, then the
 *    total. It shows only when every part can be said and the parts add up to
 *    the headline exactly; a sum that does not is never shown;
 * 5. the chance of a delayed start instead.
 *
 * Every word comes from src/copy.ts. A part the files do not give is left out,
 * and nothing is filled in.
 */

import { STATUS_KEYS, copy, format, localHour } from '../copy';
import type { BaseInput, ReasonInput, RecordCount, StatusKey } from '../copy';
import { decodeDay } from '../data/closings';
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
/** A day whose buses ran this long ago is under way: its chance is no headline. */
const UNDER_WAY_MS = 2 * HOUR_MS;
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
  /** "8:41 PM". */
  readonly time: string;
  readonly text: string;
  /** A status a district posted (its map dot), weather that happened, or what comes next. */
  readonly mark: StatusKey | 'event' | 'next';
  /** For what comes next: when, for its live countdown; null otherwise. */
  readonly at: Date | null;
}

/** A light rule across the chart at a round value. */
export interface TickView {
  readonly value: number;
  /** Pixels above the plot's foot. */
  readonly bottom: number;
  readonly label: string;
}

/** One hour's bar, in pixels above the plot's foot. */
export interface BarView {
  readonly bottom: number;
  readonly height: number;
  readonly lit: boolean;
  /** A value below 0, hanging from the zero rule. */
  readonly below: boolean;
}

/** A time along the chart's foot, under the bar at `at`. */
export interface TimeView {
  readonly at: number;
  readonly label: string;
  /** "Now", under the first hour when it is this one; else null. */
  readonly sub: string | null;
}

/** A moment marked on the chart by a thin line, its words above the plot. */
export interface FlagView {
  readonly key: 'announces' | 'buses';
  /** Where, in bars from the first bar's middle (8.5 is halfway between the 9th and 10th). */
  readonly at: number;
  readonly label: string;
  /** The side of the line its words take when there is room. */
  readonly prefer: 'left' | 'right';
  /** Where the line stops, in pixels above the plot's foot. */
  readonly downTo: number;
}

export interface ChartView {
  readonly kind: 'snow_total' | 'wind_chill';
  readonly title: string;
  /** The chart in a sentence, for a screen reader. */
  readonly summary: string;
  /** The plot's height in pixels. */
  readonly plot: number;
  readonly ticks: readonly TickView[];
  readonly bars: readonly BarView[];
  readonly times: readonly TimeView[];
  readonly flags: readonly FlagView[];
  /** The bus hour's low-to-high range, on the last bar; null without one. */
  readonly range: { readonly bottom: number; readonly height: number } | null;
  /** The words beside the last bar, centered this many pixels above the foot. */
  readonly end: { readonly label: string; readonly bottom: number };
  /** The lit hours' words: "Heaviest snow 2 to 5 AM", to the left of bar `first`. */
  readonly lit: {
    readonly label: string;
    readonly first: number;
    readonly last: number;
    /** The tallest bar top at or left of the first lit bar, in pixels. */
    readonly floor: number;
    /** The tallest lit bar's top, in pixels. */
    readonly top: number;
  } | null;
}

export interface RecordDayView {
  readonly key: string;
  readonly tone: StatusKey | 'open';
  /** "8 in", or what the district did ("Open"). */
  readonly label: string;
  /** For a screen reader: "Closed, Jan 9, 2024, 8 inches". */
  readonly spoken: string;
}

export interface WhyLineView {
  readonly key: string;
  /** "+16", "−3". */
  readonly points: string;
  readonly lead: string;
  readonly rest: string;
  readonly record: readonly RecordDayView[] | null;
}

export interface WhyView {
  /** "How we got 64%". */
  readonly title: string;
  readonly key: string;
  readonly base: {
    readonly number: string;
    readonly lead: string;
    readonly rest: string;
    readonly record: readonly RecordDayView[] | null;
  };
  readonly lines: readonly WhyLineView[];
  readonly total: { readonly number: string; readonly text: string };
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
  /** The viewer's time zone, for the live countdown. */
  readonly timeZone: string;
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

/**
 * The day the chance is for: the first of today and tomorrow that is not
 * decided and has a forecast, and whose buses have not long since run.
 */
export function headlineDay(
  outlook: Outlook,
  decided: ChanceInput['decided'],
  now: Date,
): Forecast | null {
  if (outlook === null || outlook === 'not_enough_data') return null;
  const days = [decided.today ? null : outlook.today, decided.tomorrow ? null : outlook.tomorrow];
  for (const day of days) {
    if (day?.state !== 'forecast' || day.day === undefined) continue;
    const buses = day.detail?.busesAt ?? null;
    if (buses !== null && now.getTime() - buses.getTime() > UNDER_WAY_MS) continue;
    return day;
  }
  return null;
}

/** Which way the chance moved since the run before, in whole percent, and in words. */
export function movedView(
  current: number,
  previous: ForecastDetail['previous'],
  now: Date,
  timeZone: string,
): MovedView | null {
  if (previous === null) return null;
  let text: string | null;
  try {
    text = format.moved({ previous: previous.noSchool, current, at: previous.at, now, timeZone });
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

/** The timeline: what happened and who posted, in time order, then the usual announcement. */
export function momentsOf(
  detail: ForecastDetail,
  posts: readonly Posted[],
  names: Names | null,
  input: {
    readonly day: LocalDate;
    readonly district: string;
    readonly now: Date;
    readonly timeZone: string;
  },
): MomentView[] {
  const { day, district, now, timeZone } = input;
  const happened: { at: Date; moment: MomentView }[] = [];
  const events: readonly EventDetail[] = detail.events;
  for (const event of events) {
    if (event.at > now) continue;
    happened.push({
      at: event.at,
      moment: {
        key: `event ${event.kind} ${String(event.at.getTime())}`,
        time: format.momentTime(event.at, now, timeZone),
        text: format.weatherEvent(event.kind, event.kind === 'snow_stopped' ? event.inches : null),
        mark: 'event',
        at: null,
      },
    });
  }
  for (const post of posts) {
    const name = names?.name(post.district) ?? null;
    if (name === null) continue;
    happened.push({
      at: post.at,
      moment: {
        key: `district ${String(post.district)}`,
        time: format.momentTime(post.at, now, timeZone),
        text: format.neighborPosted(name, post.status, day),
        mark: post.status,
        at: null,
      },
    });
  }
  happened.sort((a, b) => a.at.getTime() - b.at.getTime());
  const moments = happened.map((item) => item.moment);
  const at = detail.announcesAt;
  if (at !== null && now.getTime() - at.getTime() <= ANNOUNCE_GRACE_MS) {
    moments.push({
      key: 'next',
      time: format.time(at, timeZone),
      text: format.usuallyAnnounces(district),
      mark: 'next',
      at,
    });
  }
  return moments;
}

// The chart -------------------------------------------------------------------------------

/** Pixels between two light rules. */
export const TICK_PX = 40;
/** A time's words at the chart's foot, at most, and the narrowest plot they sit under. */
const TIME_LABEL_PX = 40;
const NARROWEST_PLOT_PX = 250;
const SNOW_STEPS = [0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50];
const COLD_STEPS = [5, 10, 20, 25, 40, 50];

export interface Scale {
  readonly min: number;
  readonly max: number;
  readonly step: number;
  /** The rules' values, from the foot up. */
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

/** The fewest bars between two times at the foot, so their words never meet. */
export function timeGap(count: number): number {
  return Math.max(1, Math.ceil(TIME_LABEL_PX / (NARROWEST_PLOT_PX / count)));
}

/**
 * The times at the chart's foot, by bar: the first (now) and the last (the
 * buses) always; then where the heaviest snow starts and ends, when the snow
 * starts, and every third hour, each only where it keeps clear of those placed.
 */
export function chartTimes(input: {
  readonly count: number;
  readonly start: Date;
  readonly values: readonly number[];
  readonly kind: HoursDetail['kind'];
  readonly heavy: { readonly first: number; readonly last: number } | null;
  readonly now: Date;
  readonly timeZone: string;
}): TimeView[] {
  const { count, start, values, kind, heavy, now, timeZone } = input;
  const hourOf = (at: number): Date => new Date(start.getTime() + at * HOUR_MS);
  const wanted: number[] = [0, count - 1];
  if (heavy !== null) wanted.push(heavy.first - 1, heavy.last);
  if (kind === 'snow_total') {
    const first = values.findIndex((value) => value > 0);
    if (first > 0) wanted.push(first);
  }
  for (let at = 1; at < count - 1; at++) {
    if (Number(format.shortTime(hourOf(at), timeZone).split(/\s|:/u)[0]) % 3 === 0) wanted.push(at);
  }
  const gap = timeGap(count);
  const placed: number[] = [];
  for (const at of wanted) {
    if (at < 0 || at >= count || placed.includes(at)) continue;
    if (placed.every((other) => Math.abs(other - at) >= gap)) placed.push(at);
  }
  const isNow = now >= start && now.getTime() < start.getTime() + HOUR_MS;
  return placed
    .sort((a, b) => a - b)
    .map((at) => ({
      at,
      label: format.shortTime(hourOf(at), timeZone),
      sub: at === 0 && isNow ? copy.chance.now : null,
    }));
}

/**
 * The night hour by hour, from this hour to the bus hour: bars on a scale,
 * the lit hours, the times at its foot, the two moments a family plans
 * around, and the bus hour's value (or range) beside the last bar. Null when
 * there is no series, or fewer than two of its hours are still to come.
 */
export function chartView(detail: ForecastDetail, now: Date, timeZone: string): ChartView | null {
  const { hours, busesAt, announcesAt } = detail;
  if (hours === null || busesAt === null) return null;
  // From this hour on: the hours gone by are not the night ahead.
  const gone = Math.max(0, Math.floor((now.getTime() - hours.start.getTime()) / HOUR_MS));
  const values = hours.values.slice(gone);
  if (values.length < 2) return null;
  const start = new Date(hours.start.getTime() + gone * HOUR_MS);
  const count = values.length;
  const last = values.at(-1) ?? 0;
  const scale = chartScale(hours.kind, values, hours.range?.high ?? null);
  const plot = TICK_PX * (scale.ticks.length - 1);
  const y = (value: number): number =>
    ((Math.min(scale.max, Math.max(scale.min, value)) - scale.min) / (scale.max - scale.min)) *
    plot;
  const zero = y(0);
  const heavy =
    hours.heavy === null || hours.heavy.last - gone < 0
      ? null
      : { first: Math.max(0, hours.heavy.first - gone), last: hours.heavy.last - gone };
  const bars = values.map((value, i): BarView => {
    const end = y(value);
    const height = Math.abs(end - zero);
    return {
      bottom: Math.min(zero, end),
      height: value !== 0 && height < 2 ? 2 : height,
      lit:
        hours.kind === 'snow_total'
          ? heavy !== null && i >= heavy.first && i <= heavy.last
          : i === count - 1,
      below: value < 0,
    };
  });
  const snow = hours.kind === 'snow_total';
  const unit = (value: number): string =>
    snow ? (value === 0 ? '0' : format.inches(value)) : format.degrees(value);
  const position = (instant: Date): number => (instant.getTime() - start.getTime()) / HOUR_MS;
  const flags: FlagView[] = [];
  if (announcesAt !== null) {
    const at = position(announcesAt);
    if (at >= -0.5 && at <= count - 0.5) {
      flags.push({
        key: 'announces',
        at,
        label: format.announcesFlag(announcesAt, timeZone),
        prefer: 'left',
        downTo: 0,
      });
    }
  }
  const busAt = position(busesAt);
  flags.push({
    key: 'buses',
    at: busAt,
    label: format.busesFlag(busesAt, timeZone),
    prefer: 'right',
    downTo: (snow ? y(hours.range?.high ?? last) : zero) + 3,
  });
  const evening = localHour(start, timeZone) >= 17;
  return {
    kind: hours.kind,
    title: snow ? copy.chance.snowTitle : evening ? copy.chance.coldTonight : copy.chance.coldTitle,
    summary: format.chartSummary(
      hours.kind,
      busesAt,
      hours.range?.low ?? last,
      hours.range?.high ?? last,
      timeZone,
    ),
    plot,
    ticks: scale.ticks.map((value) => ({ value, bottom: y(value), label: unit(value) })),
    bars,
    times: chartTimes({ count, start, values, kind: hours.kind, heavy, now, timeZone }),
    flags,
    range:
      hours.range === null
        ? null
        : { bottom: y(hours.range.low), height: y(hours.range.high) - y(hours.range.low) },
    end: {
      label: hours.range === null ? unit(last) : format.inches(hours.range.low, hours.range.high),
      bottom: y(last),
    },
    lit:
      heavy === null || hours.heavy === null
        ? null
        : {
            label: format.heaviest(
              new Date(hours.start.getTime() + (hours.heavy.first - 1) * HOUR_MS),
              new Date(hours.start.getTime() + hours.heavy.last * HOUR_MS),
              timeZone,
            ),
            first: heavy.first,
            last: heavy.last,
            floor: Math.max(...values.slice(0, heavy.first + 1).map((value) => y(value))),
            top: Math.max(...values.slice(heavy.first, heavy.last + 1).map((value) => y(value))),
          },
  };
}

/** A box of words along one row, in pixels from the plot's left edge. */
export interface Placed {
  readonly left: number;
  readonly row: number;
}

/**
 * Where the moments' words go above the plot: beside their line, on the side
 * each prefers, else the other; on a second row only when neither side of
 * the first is clear. Words never leave [min, max], and never meet.
 */
export function placeFlags(
  flags: readonly {
    readonly x: number;
    readonly width: number;
    readonly prefer: 'left' | 'right';
  }[],
  min: number,
  max: number,
  gap = 6,
  space = 10,
): Placed[] {
  const placed: { left: number; right: number; row: number }[] = [];
  const clear = (left: number, right: number, row: number): boolean =>
    left >= min &&
    right <= max &&
    placed.every(
      (box) => box.row !== row || right + space <= box.left || left >= box.right + space,
    );
  return flags.map(({ x, width, prefer }) => {
    const sides = prefer === 'left' ? (['left', 'right'] as const) : (['right', 'left'] as const);
    for (const row of [0, 1]) {
      for (const side of sides) {
        const left = side === 'left' ? x - gap - width : x + gap;
        if (clear(left, left + width, row)) {
          placed.push({ left, right: left + width, row });
          return { left, row };
        }
      }
    }
    // Wider than the room on either side: kept inside as far as it goes, on a row of its own.
    const left = Math.max(
      min,
      Math.min(prefer === 'left' ? x - gap - width : x + gap, max - width),
    );
    const row = placed.some((box) => box.row === 1) ? 2 : 1;
    placed.push({ left, right: left + width, row });
    return { left, row };
  });
}

/**
 * Where the lit hours' words go: to the left of the first lit bar, just above
 * every bar they pass over; else above the lit bars; else nowhere, when
 * neither fits inside the plot. In pixels: the words' left edge from the
 * plot's left, and their foot above the plot's foot.
 */
export function placeLit(input: {
  /** The first lit bar's left edge. */
  readonly runLeft: number;
  readonly width: number;
  readonly height: number;
  /** The tallest bar top at or left of the first lit bar, and the tallest lit bar's. */
  readonly floor: number;
  readonly runTop: number;
  readonly plot: number;
  /** How far left of the plot the words may go (the scale's column), and right. */
  readonly minLeft: number;
  readonly maxRight: number;
  readonly gap?: number;
}): { readonly left: number; readonly bottom: number } | null {
  const { runLeft, width, height, floor, runTop, plot, minLeft, maxRight } = input;
  const gap = input.gap ?? 6;
  const beside = { left: runLeft - 2 - width, bottom: floor + gap };
  if (beside.left >= minLeft && beside.bottom + height <= plot) return beside;
  const above = { left: runLeft, bottom: runTop + gap };
  if (above.left + width <= maxRight && above.bottom + height <= plot) return above;
  return null;
}

// How the chance adds up ------------------------------------------------------------------

/** The record's count, for the sentence that cites it; null when it is not a record of storms. */
export function recordCount(record: RecordDetail | null): RecordCount | null {
  const inches = record?.inches ?? null;
  if (record === null || inches === null) return null;
  const closed = record.days.filter((past) => past.status === 0 || past.status === 2).length;
  return { closed, days: record.days.length, inches };
}

/** The record as the map's own marks, oldest first. */
export function recordDays(record: RecordDetail): RecordDayView[] {
  return record.days.map((past) => {
    const tone: StatusKey | 'open' =
      past.status === null ? 'open' : (STATUS_KEYS[past.status] ?? 'closed');
    return {
      key: past.day,
      tone,
      label: past.inches === null ? format.recordOutcome(tone) : format.inches(past.inches),
      spoken: format.recordDay(tone, past.day, past.inches),
    };
  });
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
      return { ...reason, day };
    case 'snow_stops':
      return { ...reason, buses: detail.busesAt, day };
    case 'wind_chill':
    case 'sun':
    case 'icy_roads':
    case 'ice':
      return reason;
  }
}

/**
 * How the chance adds up, or null. Null unless the base and every reason's
 * points add up to the headline exactly, every reason can be said, and the
 * chance is neither 0 nor 100 (the headline says "<1%" or ">99%" there, and a
 * sum to 0 or 100 would claim a certainty it does not).
 */
export function whyView(input: {
  readonly detail: ForecastDetail;
  readonly chance: number;
  readonly day: LocalDate;
  readonly district: string;
  readonly names: Names | null;
  readonly now: Date;
  readonly timeZone: string;
}): WhyView | null {
  const { detail, chance, day, district, names, now, timeZone } = input;
  const why = detail.why;
  const percent = Math.round(chance * 100);
  if (why === null || percent <= 0 || percent >= 100) return null;
  const parts = [why.base.points, ...why.reasons.map((reason) => reason.points)];
  if (!parts.every((part) => Number.isInteger(part))) return null;
  if (parts.reduce((sum, part) => sum + part, 0) !== percent) return null;
  const record = detail.record;
  const shown = record === null ? null : recordDays(record);
  try {
    const base: BaseInput = why.base;
    const start = format.baseReason(base, district);
    const lines: WhyLineView[] = [];
    for (const reason of why.reasons) {
      const said = reasonInput(reason, detail, day, names);
      if (said === null) return null;
      const { lead, rest } = format.reason(said, district, now, timeZone);
      const under =
        record !== null && record.proves === reason.kind && recordCount(record) !== null
          ? shown
          : null;
      lines.push({
        key: reason.kind,
        points: format.points(reason.points),
        lead,
        rest,
        record: under,
      });
    }
    return {
      title: format.howWeGot(chance),
      key: copy.chance.key,
      base: {
        number: String(why.base.points),
        ...start,
        record: record?.proves === 'base' ? shown : null,
      },
      lines,
      total: { number: format.chanceNumber(chance), text: format.chanceOn(day) },
    };
  } catch {
    // A number the words refuse: no sum rather than a wrong one.
    return null;
  }
}

// The section -----------------------------------------------------------------------------

/**
 * The chance section, or null when there is no chance to give: no forecast
 * for a day that is not decided. Each part is null (or empty) where the files
 * do not give it; the headline shows whenever the chance itself is known.
 */
export function chanceView(input: ChanceInput): ChanceView | null {
  const { outlook, decided, status, district, closings, names, now, timeZone } = input;
  const forecast = headlineDay(outlook, decided, now);
  if (forecast?.day === undefined) return null;
  const { day, noSchool } = forecast;
  const detail = forecast.detail ?? {
    previous: null,
    announcesAt: null,
    busesAt: null,
    hours: null,
    why: null,
    record: null,
    events: [],
  };
  const neighbors =
    outlook !== null && outlook !== 'not_enough_data' ? (outlook.neighbors ?? []) : [];
  let moments: MomentView[];
  let chart: ChartView | null;
  let number: string;
  let meaning: string;
  try {
    number = format.chanceNumber(noSchool);
    meaning = format.chanceOn(day);
  } catch {
    return null;
  }
  try {
    moments = momentsOf(detail, neighborPosts(closings, day, neighbors, names, now), names, {
      day,
      district,
      now,
      timeZone,
    });
  } catch {
    moments = [];
  }
  try {
    chart = chartView(detail, now, timeZone);
  } catch {
    chart = null;
  }
  const moved = movedView(noSchool, detail.previous, now, timeZone);
  let delay: string | null = null;
  if (Math.round(forecast.delay * 100) >= 1) {
    try {
      delay = format.delayInstead(forecast.delay);
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
    why: whyView({ detail, chance: noSchool, day, district, names, now, timeZone }),
    delay,
    timeZone,
  };
}

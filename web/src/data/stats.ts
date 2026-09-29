/**
 * Reads stats/season.json and track-record.json (pipeline/snowlight/schemas/stats.py)
 * and checks each against the same rules the pipeline writes it by. A file
 * that breaks any of them reads as null, and the menu leaves its section out:
 * a count that disagrees with its parts is never shown.
 */

import type {
  Calibration,
  CalibrationBin,
  DayCounts,
  LeadRecord,
  SeasonStats,
  StateCounts,
  TrackRecord,
} from '../types/generated';

const LOCAL_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const UTC_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const SCHOOL_YEAR = /^(\d{4})-(\d{4})$/;
const USPS = /^[A-Z]{2}$/;
const MAX_COUNT = 4_294_967_294;
const MAX_LEAD_DAYS = 2;

type Fields = Record<string, unknown>;

function fields(value: unknown): Fields | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Fields)
    : null;
}

function isCount(value: unknown): value is number {
  return (
    typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= MAX_COUNT
  );
}

/** A real calendar day, YYYY-MM-DD. */
function isLocalDate(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = LOCAL_DATE.exec(value);
  if (match === null) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]) - 1, Number(match[3])];
  const date = new Date(Date.UTC(year, month, day));
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month && date.getUTCDate() === day
  );
}

function isInstant(value: unknown): value is string {
  return typeof value === 'string' && UTC_INSTANT.test(value);
}

/** The first and last day of a school year, July 1 to June 30; null for anything else. */
function schoolYearBounds(value: unknown): readonly [string, string] | null {
  if (typeof value !== 'string') return null;
  const match = SCHOOL_YEAR.exec(value);
  if (match === null || Number(match[2]) !== Number(match[1]) + 1) return null;
  return [`${match[1] ?? ''}-07-01`, `${match[2] ?? ''}-06-30`];
}

/** [key, closed, delayed, remote, early dismissal], its key checked by `key`. */
function isStatusRow(value: unknown, key: (first: unknown) => boolean): boolean {
  return (
    Array.isArray(value) &&
    value.length === 5 &&
    key(value[0]) &&
    value.slice(1).every((count) => isCount(count))
  );
}

/** The four status columns summed over rows. */
function columnSums(
  rows: readonly (readonly [string, number, number, number, number])[],
): number[] {
  const sums = [0, 0, 0, 0];
  for (const [, ...counts] of rows) {
    counts.forEach((count, column) => {
      sums[column] = (sums[column] ?? 0) + count;
    });
  }
  return sums;
}

/** stats/season.json, checked; null for anything else. */
export function parseSeasonStats(value: unknown): SeasonStats | null {
  const file = fields(value);
  if (file?.schema_version !== 1 || !isInstant(file.generated_at)) return null;
  const bounds = schoolYearBounds(file.season);
  const { through, days, states, schools, districts } = file;
  if (bounds === null || !isLocalDate(through)) return null;
  const [first, last] = bounds;
  if (through < first || through > last) return null;
  if (!Array.isArray(days) || !Array.isArray(states) || !isCount(schools) || !isCount(districts)) {
    return null;
  }
  if (!days.every((row) => isStatusRow(row, isLocalDate))) return null;
  if (
    !states.every((row) => isStatusRow(row, (code) => typeof code === 'string' && USPS.test(code)))
  ) {
    return null;
  }
  const dayRows = days as readonly DayCounts[];
  const stateRows = states as readonly StateCounts[];
  let previous = '';
  for (const [day, ...counts] of dayRows) {
    // In order, within the season so far, and each with at least one school.
    if (day < first || day > through || day <= previous) return null;
    if (counts.every((count) => count === 0)) return null;
    previous = day;
  }
  const codes = stateRows.map(([code]) => code);
  if (codes.some((code, n) => n > 0 && code <= (codes[n - 1] ?? ''))) return null;
  const byDay = columnSums(dayRows);
  const byState = columnSums(stateRows);
  if (byDay.some((sum, column) => sum !== byState[column])) return null;
  const total = byDay.reduce((sum, count) => sum + count, 0);
  if (schools > total || (schools === 0) !== (total === 0) || districts > schools) return null;
  return {
    schema_version: 1,
    generated_at: file.generated_at,
    season: file.season as string,
    through,
    days: dayRows,
    states: stateRows,
    schools,
    districts,
  };
}

function isBin(value: unknown): value is CalibrationBin {
  if (!Array.isArray(value) || value.length !== 4) return false;
  const [low, high, forecasts, outcomes] = value as unknown[];
  return (
    Number.isInteger(low) &&
    Number.isInteger(high) &&
    isCount(forecasts) &&
    isCount(outcomes) &&
    (low as number) >= 0 &&
    (high as number) <= 100 &&
    outcomes <= forecasts
  );
}

function parseCalibration(value: unknown): Calibration | null {
  const calibration = fields(value);
  if (calibration === null) return null;
  const { forecasts, outcomes, bins } = calibration;
  if (!isCount(forecasts) || !isCount(outcomes) || !Array.isArray(bins) || bins.length === 0) {
    return null;
  }
  if (!bins.every(isBin)) return null;
  // From 0 to 100 without gaps, adding up to the totals.
  let edge = 0;
  let given = 0;
  let happened = 0;
  for (const [low, high, binForecasts, binOutcomes] of bins as readonly CalibrationBin[]) {
    if (low !== edge || high <= low) return null;
    edge = high;
    given += binForecasts;
    happened += binOutcomes;
  }
  if (edge !== 100 || given !== forecasts || happened !== outcomes) return null;
  return { forecasts, outcomes, bins };
}

function parseLead(value: unknown): LeadRecord | null {
  const lead = fields(value);
  if (lead === null) return null;
  const leadDays = lead.lead_days;
  if (typeof leadDays !== 'number' || !Number.isInteger(leadDays)) return null;
  if (leadDays < 0 || leadDays > MAX_LEAD_DAYS) return null;
  const noSchool = parseCalibration(lead.no_school);
  const delay = parseCalibration(lead.delay);
  if (noSchool === null || delay === null) return null;
  return { lead_days: leadDays, no_school: noSchool, delay };
}

/** track-record.json, checked; null for anything else. */
export function parseTrackRecord(value: unknown): TrackRecord | null {
  const file = fields(value);
  if (file?.schema_version !== 1 || !isInstant(file.generated_at)) return null;
  const { first_day: firstDay, last_day: lastDay } = file;
  if (!Array.isArray(file.leads)) return null;
  const leads: LeadRecord[] = [];
  for (const raw of file.leads) {
    const lead = parseLead(raw);
    // Sorted by how far ahead, each once.
    if (lead === null || lead.lead_days <= (leads.at(-1)?.lead_days ?? -1)) return null;
    leads.push(lead);
  }
  const scored = leads.some((lead) => lead.no_school.forecasts > 0 || lead.delay.forecasts > 0);
  // Both null until a day is scored; then both set, the first no later than the last.
  if (firstDay === null && lastDay === null) {
    if (scored) return null;
    return {
      schema_version: 1,
      generated_at: file.generated_at,
      first_day: null,
      last_day: null,
      leads,
    };
  }
  if (!isLocalDate(firstDay) || !isLocalDate(lastDay) || firstDay > lastDay || !scored) return null;
  return {
    schema_version: 1,
    generated_at: file.generated_at,
    first_day: firstDay,
    last_day: lastDay,
    leads,
  };
}

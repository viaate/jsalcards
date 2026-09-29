/**
 * The menu's view: what its pages show from the published files, each part
 * only when a file gives it, worded here from src/copy.ts so the panel
 * (ui/MenuPanel.svelte) composes no words. The season and the track record
 * are pages of their own, listed only when they have something to show; what
 * the map holds is on About's page.
 *
 * - Season stats, from stats/season.json: how many schools and districts
 *   weather has closed, delayed, sent home early or kept remote this school
 *   year, each status's school-days, and the busiest day.
 * - Track record, from track-record.json: for each chance of no school the
 *   site has given, how many of those days had none, by how far ahead it was
 *   given.
 * - On the map, from the school directory's stamp (schools/details/index.json):
 *   how many schools and districts the map holds.
 *
 * A file this build does not ship is never asked for, and one that cannot be
 * read or breaks its rules (data/stats.ts) leaves its part out. Nothing is
 * filled in, and no part says it has nothing to show.
 */

import { STATUS_KEYS, copy } from '../copy';
import { format } from '../copy-format';
import type { StatusKey } from '../copy';
import { DETAILS_INDEX_PATH } from '../data/details-format';
import { parseShardIndex } from '../data/details';
import { fetchJson } from '../data/files';
import type { DataFiles, Fetch } from '../data/files';
import { parseSeasonStats, parseTrackRecord } from '../data/stats';
import { PUBLISHED_PATHS } from '../types/generated';
import type { DirectoryStamp, SeasonStats, TrackRecord } from '../types/generated';

/** One line of a list: a label, its value, and the status it counts, if any. */
export interface MenuRow {
  readonly label: string;
  readonly value: string;
  /** The status whose mark sits beside the label; null for a plain row. */
  readonly tone: StatusKey | null;
}

/** A part of the menu: its heading, a line under it, and its rows. */
export interface MenuSection {
  readonly title: string;
  /** Across from the heading, in its style: the season and its last day. Null for none. */
  readonly note: string | null;
  readonly rows: readonly MenuRow[];
}

/** The track record: one row per chance given, one column per how far ahead. */
export interface RecordTable {
  readonly title: string;
  /** The days it covers. */
  readonly note: string;
  /** What a cell counts. */
  readonly caption: string;
  /** The heads: the chance given, then each lead. */
  readonly columns: readonly string[];
  readonly rows: readonly { readonly label: string; readonly cells: readonly (string | null)[] }[];
}

export interface MenuView {
  readonly season: MenuSection | null;
  readonly record: RecordTable | null;
  readonly map: MenuSection | null;
}

/** What parts a line in two, as copy.ts's own lines are parted: "2025–26 · Through Jan 12". */
const DOT = ' · ';

/** Each status's school-days, in the order the legend keys them. */
const STATUS_LABELS: Readonly<Record<StatusKey, string>> = {
  closed: copy.season.closures,
  delayed: copy.season.delays,
  remote: copy.season.remote,
  earlyDismissal: copy.season.earlyDismissals,
};

/** The season so far: null while no day has an affected school. */
export function seasonSection(stats: SeasonStats | null): MenuSection | null {
  if (stats === null || stats.days.length === 0 || stats.schools === 0) return null;
  const rows: MenuRow[] = [
    { label: copy.season.schoolsAffected, value: format.number(stats.schools), tone: null },
  ];
  if (stats.districts > 0) {
    rows.push({
      label: copy.season.districtsAffected,
      value: format.number(stats.districts),
      tone: null,
    });
  }
  STATUS_KEYS.forEach((status, column) => {
    let total = 0;
    for (const day of stats.days) total += day[column + 1] as number;
    if (total > 0)
      rows.push({ label: STATUS_LABELS[status], value: format.number(total), tone: status });
  });
  // The day with the most schools affected; the first of any tie.
  let busiest: { day: string; schools: number } | null = null;
  for (const [day, ...counts] of stats.days) {
    const schools = counts.reduce((sum, count) => sum + count, 0);
    if (busiest === null || schools > busiest.schools) busiest = { day, schools };
  }
  if (busiest !== null) {
    rows.push({
      label: copy.season.busiestDay,
      value: `${format.day(busiest.day)}${DOT}${format.schools(busiest.schools)}`,
      tone: null,
    });
  }
  return {
    title: copy.nav.seasonStats,
    note: `${format.season(stats.season)}${DOT}${format.through(stats.through)}`,
    rows,
  };
}

/**
 * The track record for no school: each chance given, and how many of the
 * district-days given it had no school, by lead. Null until a day is scored.
 */
export function recordTable(record: TrackRecord | null): RecordTable | null {
  if (record === null) return null;
  const { first_day: first, last_day: last } = record;
  if (first === null || last === null) return null;
  const leads = record.leads.filter((lead) => lead.no_school.forecasts > 0);
  if (leads.length === 0) return null;
  // Every lead's bins run 0 to 100; a row for each range any lead gave a chance in.
  const ranges = new Map<string, { low: number; high: number }>();
  for (const lead of leads) {
    for (const [low, high, forecasts] of lead.no_school.bins) {
      if (forecasts > 0) ranges.set(`${String(low)}-${String(high)}`, { low, high });
    }
  }
  const rows = [...ranges.values()]
    .sort((a, b) => a.low - b.low || a.high - b.high)
    .map(({ low, high }) => ({
      label: format.percentRange(low, high),
      cells: leads.map((lead) => {
        const bin = lead.no_school.bins.find(([from, to]) => from === low && to === high);
        return bin === undefined || bin[2] === 0 ? null : format.outOf(bin[3], bin[2]);
      }),
    }));
  return {
    title: copy.nav.trackRecord,
    note: format.span(first, last),
    caption: copy.trackRecord.caption,
    columns: [copy.trackRecord.chanceGiven, ...leads.map((lead) => format.lead(lead.lead_days))],
    rows,
  };
}

/** What the map holds: every school and district in the directory. */
export function mapSection(directory: DirectoryStamp | null): MenuSection | null {
  if (directory === null || directory.schools === 0) return null;
  return {
    title: copy.menu.onMap,
    note: null,
    rows: [
      { label: copy.menu.schools, value: format.number(directory.schools), tone: null },
      { label: copy.menu.districts, value: format.number(directory.districts), tone: null },
    ],
  };
}

/** A shipped file, read and checked; null when it is not shipped or does not pass. */
async function read<T>(
  files: DataFiles,
  path: string,
  parse: (value: unknown) => T | null,
  fetchImpl?: Fetch,
): Promise<T | null> {
  if (!files.has(path)) return null;
  try {
    return parse(await fetchJson(files, path, {}, fetchImpl));
  } catch {
    return null;
  }
}

/** Reads what the menu shows beside About; parts whose files are missing or wrong are left out. */
export async function readMenu(files: DataFiles, fetchImpl?: Fetch): Promise<MenuView> {
  const [season, record, index] = await Promise.all([
    read(files, PUBLISHED_PATHS.seasonStats, parseSeasonStats, fetchImpl),
    read(files, PUBLISHED_PATHS.trackRecord, parseTrackRecord, fetchImpl),
    read(files, DETAILS_INDEX_PATH, parseShardIndex, fetchImpl),
  ]);
  return {
    season: seasonSection(season),
    record: recordTable(record),
    map: mapSection(index?.directory ?? null),
  };
}

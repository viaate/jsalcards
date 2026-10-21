/**
 * What the admin view's overview reads besides the accounts API: the latest
 * run of each workflow and the open issues (the public GitHub API, read from
 * the browser without a token, so it is rate limited per network), and a
 * summary of the predictions file. Every read can fail on its own; a failed
 * one shows as not readable, never as a guess.
 */

import { format } from '../copy-format';
import { sameDirectory, type Directory, type Points } from '../data/directory';
import { nextDay, rowOn } from '../data/school-day';
import {
  Status,
  type ClosingsFile,
  type LocalDate,
  type PredictionsFile,
} from '../types/generated';

/** The repository the site is built from (VITE_GITHUB_REPO, set by preview.yml). */
const REPO_SET = import.meta.env.VITE_GITHUB_REPO ?? '';
export const REPO = /^[\w.-]+\/[\w.-]+$/.test(REPO_SET) ? REPO_SET : 'viaate/jsalcards';

export const WORKFLOWS = [
  ['predict', 'predict.yml'],
  ['liveIngest', 'live-ingest.yml'],
  ['api', 'api.yml'],
  ['ci', 'ci.yml'],
  ['preview', 'preview.yml'],
] as const;

export type WorkflowKey = (typeof WORKFLOWS)[number][0];
export type RunState =
  'success' | 'failure' | 'cancelled' | 'skipped' | 'running' | 'queued' | 'other' | 'never';

export interface RunSummary {
  readonly workflow: WorkflowKey;
  /** null when the run could not be read. */
  readonly state: RunState | null;
  readonly at: string | null;
  readonly url: string | null;
}

export interface Issue {
  readonly title: string;
  readonly url: string;
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

export function runState(run: { status?: unknown; conclusion?: unknown }): RunState {
  if (run.status === 'queued' || run.status === 'waiting' || run.status === 'pending')
    return 'queued';
  if (run.status !== 'completed') return 'running';
  switch (run.conclusion) {
    case 'success':
      return 'success';
    case 'failure':
    case 'timed_out':
    case 'startup_failure':
      return 'failure';
    case 'cancelled':
      return 'cancelled';
    case 'skipped':
      return 'skipped';
    default:
      return 'other';
  }
}

/** True when GitHub refused the read for its rate limit. */
function limited(response: Response): boolean {
  return (
    (response.status === 403 || response.status === 429) &&
    response.headers.get('x-ratelimit-remaining') === '0'
  );
}

export async function readRuns(
  fetcher: Fetcher = (url, init) => fetch(url, init),
  repo: string = REPO,
): Promise<{ runs: RunSummary[]; limited: boolean }> {
  let hitLimit = false;
  const runs = await Promise.all(
    WORKFLOWS.map(async ([workflow, file]): Promise<RunSummary> => {
      try {
        const response = await fetcher(
          `https://api.github.com/repos/${repo}/actions/workflows/${file}/runs?per_page=1&exclude_pull_requests=true`,
          { headers: { Accept: 'application/vnd.github+json' }, credentials: 'omit' },
        );
        if (response.status === 404) return { workflow, state: 'never', at: null, url: null };
        if (!response.ok) {
          if (limited(response)) hitLimit = true;
          return { workflow, state: null, at: null, url: null };
        }
        const body = (await response.json()) as { workflow_runs?: unknown };
        const run = Array.isArray(body.workflow_runs)
          ? (body.workflow_runs[0] as Record<string, unknown> | undefined)
          : undefined;
        if (run === undefined) return { workflow, state: 'never', at: null, url: null };
        return {
          workflow,
          state: runState(run),
          at: typeof run.updated_at === 'string' ? run.updated_at : null,
          url:
            typeof run.html_url === 'string' && run.html_url.startsWith('https://github.com/')
              ? run.html_url
              : null,
        };
      } catch {
        return { workflow, state: null, at: null, url: null };
      }
    }),
  );
  return { runs, limited: hitLimit };
}

export async function readIssues(
  fetcher: Fetcher = (url, init) => fetch(url, init),
  repo: string = REPO,
): Promise<{ issues: Issue[] | null; limited: boolean }> {
  try {
    const response = await fetcher(
      `https://api.github.com/repos/${repo}/issues?state=open&per_page=20`,
      { headers: { Accept: 'application/vnd.github+json' }, credentials: 'omit' },
    );
    if (!response.ok) return { issues: null, limited: limited(response) };
    const body: unknown = await response.json();
    if (!Array.isArray(body)) return { issues: null, limited: false };
    const issues = body
      .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
      // The issues list holds pull requests too.
      .filter((item) => item.pull_request === undefined)
      .filter(
        (item) =>
          typeof item.title === 'string' &&
          typeof item.html_url === 'string' &&
          item.html_url.startsWith('https://github.com/'),
      )
      .map((item) => ({ title: item.title as string, url: item.html_url as string }));
    return { issues, limited: false };
  } catch {
    return { issues: null, limited: false };
  }
}

export interface ChanceRow {
  readonly district: number;
  readonly chance: number;
}

export interface PredictionSummary {
  readonly generatedAt: string;
  /** Districts at 50% or more, for the file's first day and its second (null without one). */
  readonly today: number;
  readonly tomorrow: number | null;
  /** The 20 highest chances of no school on the first day, highest first. */
  readonly top: readonly ChanceRow[];
}

function chanceOn(day: unknown): number | null {
  if (typeof day !== 'object' || day === null) return null;
  const forecast = day as { state?: unknown; p_no_school?: unknown };
  return forecast.state === 'forecast' && typeof forecast.p_no_school === 'number'
    ? forecast.p_no_school
    : null;
}

export function summarizePredictions(file: PredictionsFile): PredictionSummary {
  let today = 0;
  let tomorrow = 0;
  const rows: ChanceRow[] = [];
  for (const forecast of file.districts) {
    const first = chanceOn(forecast.days[0]);
    const second = chanceOn(forecast.days[1]);
    if (first !== null) {
      rows.push({ district: forecast.district, chance: first });
      if (first >= 0.5) today++;
    }
    if (second !== null && second >= 0.5) tomorrow++;
  }
  rows.sort((a, b) => b.chance - a.chance || a.district - b.district);
  return {
    generatedAt: file.generated_at,
    today,
    tomorrow: file.days.length > 1 ? tomorrow : null,
    top: rows.slice(0, 20),
  };
}

/** The hour of the day at `at` in `timeZone` (0-23). */
function localHour(at: Date, timeZone: string): number {
  const hour = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    hour: '2-digit',
  }).format(at);
  return Number(hour);
}

/** The hour a school day is over, school-local (as the weights take it). */
export const SCHOOL_DAY_ENDS_HOUR = 15;

/** Which days a manual status lists, as the admin picks them. */
export type DayChoice = 'today' | 'tomorrow' | 'both';

/**
 * The days the form offers first: today, or tomorrow once the school's day is
 * over in its zone.
 */
export function defaultDays(now: Date, timeZone: string): DayChoice {
  return localHour(now, timeZone) >= SCHOOL_DAY_ENDS_HOUR ? 'tomorrow' : 'today';
}

/** The school's today and tomorrow in `timeZone`, as local dates. */
export function schoolDays(now: Date, timeZone: string): { today: LocalDate; tomorrow: LocalDate } {
  const today = format.localDay(now, timeZone);
  return { today, tomorrow: nextDay(today) };
}

/** A day choice the form offers, with the dates it lists (ascending): what the API stores. */
export interface DayOption {
  readonly choice: DayChoice;
  readonly days: readonly LocalDate[];
}

/** The form's day choices at `now`, in the school's zone: today, tomorrow, and both. */
export function dayOptions(now: Date, timeZone: string): readonly DayOption[] {
  const { today, tomorrow } = schoolDays(now, timeZone);
  return [
    { choice: 'today', days: [today] },
    { choice: 'tomorrow', days: [tomorrow] },
    { choice: 'both', days: [today, tomorrow] },
  ];
}

export function sameDays(a: readonly LocalDate[] | null, b: readonly LocalDate[]): boolean {
  return a !== null && a.length === b.length && a.every((day, i) => day === b[i]);
}

/**
 * The dates the admin picked, to send: the exact dates the choice showed when
 * it was picked, while the form still offers them at `now` (the school's
 * midnight can pass between the pick and the save: "Tomorrow (Wed)" picked at
 * 11:59 PM is then "Today (Wed)", and still Wednesday). Null once they are
 * not offered any more ("Today (Tue)" after midnight): the admin picks again.
 */
export function offeredDays(
  chosen: readonly LocalDate[] | null,
  now: Date,
  timeZone: string,
): LocalDate[] | null {
  if (chosen === null) return null;
  return dayOptions(now, timeZone).some((option) => sameDays(chosen, option.days))
    ? [...chosen]
    : null;
}

/**
 * Each district's time zone as the predictions file gives it, by district
 * position: the zones the overrides pass lights days in (the committed
 * model's). Null without a file, or for a file of another directory edition,
 * whose positions name other districts.
 */
export function predictionZones(
  directory: Directory | null,
  predictions: PredictionsFile | null,
): ReadonlyMap<number, string> | null {
  if (directory === null || predictions === null) return null;
  if (!sameDirectory(directory, predictions.directory)) return null;
  return new Map(predictions.districts.map((entry) => [entry.district, entry.time_zone]));
}

const MICRO = 1e6;

/**
 * The zone of the school nearest `school` among those whose district has a
 * zone, as the overrides pass gives a school without a district its zone
 * (pipeline/snowlight/live/overrides.py, DeployedSchools.borrowed_zones: the
 * same places in microdegrees, the same distance, the first nearest by
 * position). Its golden file keeps the two the same.
 */
export function nearestZone(
  points: Pick<Points, 'lngLat' | 'district'>,
  zones: ReadonlyMap<number, string>,
  school: number,
): string | null {
  const count = points.district.length;
  if (school < 0 || school >= count) return null;
  const micro = (at: number): number => Math.round((points.lngLat[at] ?? Number.NaN) * MICRO);
  const hereLon = micro(school * 2) / MICRO;
  const hereLat = micro(school * 2 + 1) / MICRO;
  const scale = Math.cos(hereLat * (Math.PI / 180));
  let best = Number.POSITIVE_INFINITY;
  let found: string | null = null;
  for (let i = 0; i < count; i++) {
    const zone = zones.get(points.district[i] ?? -1);
    if (zone === undefined) continue;
    const east = (micro(i * 2) / MICRO - hereLon) * scale;
    const north = micro(i * 2 + 1) / MICRO - hereLat;
    const distance = east * east + north * north;
    if (distance < best) {
      best = distance;
      found = zone;
    }
  }
  return found;
}

/**
 * The zone a manual status's days are named in, the one the overrides pass
 * lights them in: the district's (for a district, or a school in one), or
 * for a school without a district the nearest zoned school's. Null when it
 * cannot be known here: the form then sets nothing.
 */
export function statusZone(
  directory: Directory | null,
  predictions: PredictionsFile | null,
  district: number,
  school: number,
): string | null {
  const zones = predictionZones(directory, predictions);
  if (zones === null || directory === null) return null;
  if (district >= 0) return zones.get(district) ?? null;
  return nearestZone(directory, zones, school);
}

const STATUS_CODES: Readonly<Record<string, Status>> = {
  closed: Status.closed,
  delayed: Status.delayed,
  early_dismissal: Status.early_dismissal,
};

/** What of a manual status the map is checked for on one of its days. */
export interface ListedStatus {
  readonly status: 'closed' | 'delayed' | 'early_dismissal' | 'open';
  readonly minutes: number | null;
  readonly at_local_time: string | null;
  readonly set_at: string;
}

/**
 * Whether live/closings.json carries a manual status on `day` for the school
 * at `school` (its position in `directory`) exactly: the row the admin's
 * status publishes, set by the site's team, with its status, delay and time.
 * An Open is on the map once a file published after it was set holds no row
 * for that day. A file for another directory, or none, carries nothing.
 */
export function onTheMap(
  closings: ClosingsFile | null,
  directory: Directory | null,
  school: number,
  day: LocalDate,
  item: ListedStatus,
): boolean {
  if (closings === null || directory === null || !sameDirectory(directory, closings.directory)) {
    return false;
  }
  const row = rowOn(closings, day, school);
  if (item.status === 'open') {
    const published = Date.parse(closings.generated_at);
    return row === null && Number.isFinite(published) && published >= Date.parse(item.set_at);
  }
  if (row === null || !row.manual || row.status !== STATUS_CODES[item.status]) return false;
  const [hours, minutes] = (item.at_local_time ?? '').split(':').map(Number);
  const clock =
    item.status === 'early_dismissal' && hours !== undefined && minutes !== undefined
      ? hours * 60 + minutes
      : null;
  const shift = item.status === 'delayed' ? item.minutes : null;
  return row.shiftMinutes === shift && row.clockMinute === clock;
}

/** A manual status as the admin list has it, for which schools it lights. */
export interface ListedTarget {
  readonly scope: 'district' | 'school';
  readonly id: string;
  readonly days: readonly LocalDate[];
}

/** What the map shows of a manual status on one of its days. */
export type DayState = 'onMap' | 'waiting' | 'shadowed';

/**
 * The schools `item` lights on `day` (positions in `directory`), as the
 * overrides pass merges them: a school's own status at that school; a
 * district's at each of its schools, less those with a school status of
 * their own in `active` that lists that day (the school's own wins there).
 */
export function litSchools(
  directory: Directory,
  item: ListedTarget,
  day: LocalDate,
  active: readonly ListedTarget[],
): number[] {
  if (item.scope === 'school') {
    const school = directory.schoolIndex(item.id);
    return school >= 0 ? [school] : [];
  }
  const district = directory.districtIndex(item.id);
  if (district < 0) return [];
  const own = new Set(
    active
      .filter((other) => other.scope === 'school' && other.days.includes(day))
      .map((other) => directory.schoolIndex(other.id)),
  );
  const found: number[] = [];
  for (let school = 0; school < directory.district.length; school++) {
    if (directory.district[school] === district && !own.has(school)) found.push(school);
  }
  return found;
}

/**
 * Whether the map shows `item` on `day`: on the map once live/closings.json
 * carries it exactly (onTheMap) at every school it lights there; shadowed
 * when each of its district's schools has a school status of its own that
 * day, so it lights none; waiting otherwise (and with no file, a file of
 * another directory, or no directory yet).
 */
export function dayState(
  closings: ClosingsFile | null,
  directory: Directory | null,
  item: ListedTarget & ListedStatus,
  day: LocalDate,
  active: readonly ListedTarget[],
): DayState {
  if (directory === null) return 'waiting';
  const schools = litSchools(directory, item, day, active);
  if (schools.length === 0) {
    // Its district has schools, and each has its own status that day.
    return litSchools(directory, item, day, []).length > 0 ? 'shadowed' : 'waiting';
  }
  return schools.every((school) => onTheMap(closings, directory, school, day, item))
    ? 'onMap'
    : 'waiting';
}

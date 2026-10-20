/**
 * What the admin view's overview reads besides the accounts API: the latest
 * run of each workflow and the open issues (the public GitHub API, read from
 * the browser without a token, so it is rate limited per network), and a
 * summary of the predictions file. Every read can fail on its own; a failed
 * one shows as not readable, never as a guess.
 */

import { copy, type StatusKey } from '../copy';
import type { SchoolView } from '../app/school';
import type { PredictionsFile } from '../types/generated';

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

/** The UTC offset of `timeZone` at `at`, in ms (local minus UTC). */
function offsetAt(at: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(at));
  const get = (type: string): number => Number(parts.find((p) => p.type === type)?.value ?? '0');
  const local = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour'),
    get('minute'),
    get('second'),
  );
  return local - Math.floor(at / 1000) * 1000;
}

/**
 * 23:59 on the local day `after` days from now's, in `timeZone`, as an
 * instant: where a manual status ends by default.
 */
export function endOfLocalDay(now: Date, timeZone: string, after = 0): Date {
  const today = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
  const [y, m, d] = today.split('-').map(Number) as [number, number, number];
  const wall = Date.UTC(y, m - 1, d + after, 23, 59, 0);
  let at = wall - offsetAt(wall, timeZone);
  // Across a change of clocks the offset at the answer can differ from the guess's.
  at = wall - offsetAt(at, timeZone);
  return new Date(at);
}

/**
 * Each state's easternmost time zone: where a school's own zone is not known
 * (no predictions file), its day is taken to end no later than it really
 * does, so a manual status never outlasts its day.
 */
export const STATE_ZONES: Readonly<Record<string, string>> = {
  AL: 'America/Chicago',
  AK: 'America/Anchorage',
  AZ: 'America/Phoenix',
  AR: 'America/Chicago',
  CA: 'America/Los_Angeles',
  CO: 'America/Denver',
  CT: 'America/New_York',
  DE: 'America/New_York',
  DC: 'America/New_York',
  FL: 'America/New_York',
  GA: 'America/New_York',
  HI: 'Pacific/Honolulu',
  ID: 'America/Denver',
  IL: 'America/Chicago',
  IN: 'America/New_York',
  IA: 'America/Chicago',
  KS: 'America/Chicago',
  KY: 'America/New_York',
  LA: 'America/Chicago',
  ME: 'America/New_York',
  MD: 'America/New_York',
  MA: 'America/New_York',
  MI: 'America/New_York',
  MN: 'America/Chicago',
  MS: 'America/Chicago',
  MO: 'America/Chicago',
  MT: 'America/Denver',
  NE: 'America/Chicago',
  NV: 'America/Denver',
  NH: 'America/New_York',
  NJ: 'America/New_York',
  NM: 'America/Denver',
  NY: 'America/New_York',
  NC: 'America/New_York',
  ND: 'America/Chicago',
  OH: 'America/New_York',
  OK: 'America/Chicago',
  OR: 'America/Denver',
  PA: 'America/New_York',
  RI: 'America/New_York',
  SC: 'America/New_York',
  SD: 'America/Chicago',
  TN: 'America/New_York',
  TX: 'America/Chicago',
  UT: 'America/Denver',
  VT: 'America/New_York',
  VA: 'America/New_York',
  WA: 'America/Los_Angeles',
  WV: 'America/New_York',
  WI: 'America/Chicago',
  WY: 'America/Denver',
};

/** A manual status, as the map's panel would show it for today. */
const TONES: Readonly<Record<string, StatusKey | 'open'>> = {
  closed: 'closed',
  delayed: 'delayed',
  early_dismissal: 'earlyDismissal',
  open: 'open',
};

/**
 * Whether the map shows `status` for the school today: its panel's line for
 * today has that status. Anything else (another status, none, a line for
 * tomorrow only, a panel still loading) is not on the map yet.
 */
export function showsToday(view: SchoolView | null, status: string): boolean {
  const tone = TONES[status];
  if (view === null || view.loading || tone === undefined) return false;
  const headline = tone === 'open' ? copy.open.today : copy.statusLine[tone].today;
  return view.status.some((line) => line.tone === tone && line.headline === headline);
}

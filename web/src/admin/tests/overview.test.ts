import { describe, expect, it } from 'vitest';

import { copy } from '../../copy';
import type { SchoolView } from '../../app/school';
import type { PredictionsFile } from '../../types/generated';
import {
  STATE_ZONES,
  endOfLocalDay,
  readIssues,
  readRuns,
  runState,
  showsToday,
  summarizePredictions,
} from '../overview';

describe('runState', () => {
  it('reads a run’s status and conclusion', () => {
    expect(runState({ status: 'completed', conclusion: 'success' })).toBe('success');
    expect(runState({ status: 'completed', conclusion: 'timed_out' })).toBe('failure');
    expect(runState({ status: 'completed', conclusion: 'cancelled' })).toBe('cancelled');
    expect(runState({ status: 'in_progress', conclusion: null })).toBe('running');
    expect(runState({ status: 'queued', conclusion: null })).toBe('queued');
    expect(runState({ status: 'completed', conclusion: 'neutral' })).toBe('other');
  });
});

describe('the GitHub reads', () => {
  const json = (body: unknown, status = 200, headers: Record<string, string> = {}): Response =>
    new Response(JSON.stringify(body), { status, headers });

  it('takes each workflow’s latest run, and says when none ran', async () => {
    const runs = await readRuns((url) =>
      Promise.resolve(
        url.includes('/api.yml/')
          ? json({ workflow_runs: [] })
          : json({
              workflow_runs: [
                {
                  status: 'completed',
                  conclusion: 'failure',
                  updated_at: '2026-10-20T18:00:00Z',
                  html_url: 'https://github.com/o/r/actions/runs/1',
                },
              ],
            }),
      ),
    );
    expect(runs.limited).toBe(false);
    expect(runs.runs.find((r) => r.workflow === 'api')?.state).toBe('never');
    expect(runs.runs.find((r) => r.workflow === 'ci')).toEqual({
      workflow: 'ci',
      state: 'failure',
      at: '2026-10-20T18:00:00Z',
      url: 'https://github.com/o/r/actions/runs/1',
    });
  });

  it('says when GitHub limits the reads, and shows nothing it could not read', async () => {
    const limited = await readRuns(() =>
      Promise.resolve(json({}, 403, { 'x-ratelimit-remaining': '0' })),
    );
    expect(limited.limited).toBe(true);
    expect(limited.runs.every((r) => r.state === null)).toBe(true);
    const down = await readRuns(() => Promise.reject(new Error('offline')));
    expect(down.runs.every((r) => r.state === null)).toBe(true);
  });

  it('lists open issues without pull requests or links off GitHub', async () => {
    const { issues } = await readIssues(() =>
      Promise.resolve(
        json([
          { title: 'Chances went dark', html_url: 'https://github.com/o/r/issues/1' },
          { title: 'A PR', html_url: 'https://github.com/o/r/pull/2', pull_request: {} },
          { title: 'Odd', html_url: 'javascript:alert(1)' },
        ]),
      ),
    );
    expect(issues).toEqual([
      { title: 'Chances went dark', url: 'https://github.com/o/r/issues/1' },
    ]);
  });
});

describe('summarizePredictions', () => {
  it('counts districts at 50% or more and ranks the highest', () => {
    const forecast = (p: number) => ({ state: 'forecast', p_no_school: p });
    const file = {
      generated_at: '2026-10-20T12:00:00Z',
      days: ['2026-10-20', '2026-10-21'],
      districts: [
        { district: 0, days: [forecast(0.7), forecast(0.2)] },
        { district: 1, days: [forecast(0.5), forecast(0.9)] },
        { district: 2, days: [{ state: 'no_threat' }, forecast(0.6)] },
        { district: 3, days: [forecast(0.1), { state: 'no_threat' }] },
      ],
    } as unknown as PredictionsFile;
    const summary = summarizePredictions(file);
    expect(summary.today).toBe(2);
    expect(summary.tomorrow).toBe(2);
    expect(summary.top.map((r) => r.district)).toEqual([0, 1, 3]);
  });
});

describe('endOfLocalDay', () => {
  it('ends at 23:59 in the school’s zone, across a change of clocks', () => {
    const now = new Date('2026-11-01T15:00:00Z');
    expect(endOfLocalDay(now, 'America/New_York').toISOString()).toBe('2026-11-02T04:59:00.000Z');
    expect(endOfLocalDay(now, 'America/Chicago', 1).toISOString()).toBe('2026-11-03T05:59:00.000Z');
    // Late at night in UTC it is still the evening before in Denver.
    expect(endOfLocalDay(new Date('2026-01-15T03:00:00Z'), 'America/Denver').toISOString()).toBe(
      '2026-01-15T06:59:00.000Z',
    );
  });

  it('knows every state’s easternmost zone', () => {
    expect(Object.keys(STATE_ZONES)).toHaveLength(51);
    expect(STATE_ZONES.TN).toBe('America/New_York');
  });
});

describe('showsToday', () => {
  const view = (tone: string, headline: string, loading = false): SchoolView =>
    ({ loading, status: [{ tone, headline, detail: null, note: null }] }) as unknown as SchoolView;

  it('is true only when today’s line has that status', () => {
    expect(showsToday(view('closed', copy.statusLine.closed.today), 'closed')).toBe(true);
    expect(showsToday(view('closed', copy.statusLine.closed.tomorrow), 'closed')).toBe(false);
    expect(showsToday(view('delayed', copy.statusLine.delayed.today), 'closed')).toBe(false);
    expect(showsToday(view('closed', copy.statusLine.closed.today, true), 'closed')).toBe(false);
    expect(showsToday(view('open', copy.open.today), 'open')).toBe(true);
    expect(showsToday(null, 'closed')).toBe(false);
  });
});

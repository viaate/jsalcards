import { describe, expect, it, vi } from 'vitest';

import { copy, format } from '../../copy';
import { createDataFiles } from '../../data/files';
import type { Calibration, SeasonStats, TrackRecord } from '../../types/generated';
import { mapSection, readMenu, recordTable, seasonSection } from '../menu';

const ROOT = 'https://snow.test/data/';

/** A season in the published shape, made up for these tests. */
const SEASON: SeasonStats = {
  schema_version: 1,
  generated_at: '2026-01-13T12:00:00Z',
  season: '2025-2026',
  through: '2026-01-13',
  days: [
    ['2026-01-05', 10, 4, 0, 1],
    ['2026-01-12', 30, 6, 0, 0],
    ['2026-01-13', 20, 16, 0, 0],
  ],
  states: [
    ['IA', 25, 10, 0, 1],
    ['MO', 35, 16, 0, 0],
  ],
  schools: 51,
  districts: 9,
};

/** Bins in tens from [forecasts, outcomes] pairs. */
function calibration(pairs: readonly (readonly [number, number])[]): Calibration {
  return {
    forecasts: pairs.reduce((sum, [forecasts]) => sum + forecasts, 0),
    outcomes: pairs.reduce((sum, [, outcomes]) => sum + outcomes, 0),
    bins: pairs.map(([forecasts, outcomes], n) => [n * 10, (n + 1) * 10, forecasts, outcomes]),
  };
}

const EMPTY_BINS = Array.from({ length: 10 }, () => [0, 0] as const);
const NONE = calibration(EMPTY_BINS);

const RECORD: TrackRecord = {
  schema_version: 1,
  generated_at: '2026-01-13T12:00:00Z',
  first_day: '2025-12-01',
  last_day: '2026-01-13',
  leads: [
    {
      lead_days: 0,
      no_school: calibration([[40, 1], [12, 2], ...EMPTY_BINS.slice(2, 9), [4, 4]]),
      delay: NONE,
    },
    {
      lead_days: 1,
      no_school: calibration([[38, 2], [0, 0], [6, 3], ...EMPTY_BINS.slice(3)]),
      delay: NONE,
    },
    { lead_days: 2, no_school: NONE, delay: calibration([[5, 1], ...EMPTY_BINS.slice(1)]) },
  ],
};

describe('seasonSection', () => {
  it('counts the season: schools, districts, each status’s school-days, and the busiest day', () => {
    const section = seasonSection(SEASON);
    expect(section?.title).toBe(copy.nav.seasonStats);
    expect(section?.note).toBe(`${format.season('2025-2026')} · ${format.through('2026-01-13')}`);
    expect(section?.rows).toEqual([
      { label: copy.season.schoolsAffected, value: '51', tone: null },
      { label: copy.season.districtsAffected, value: '9', tone: null },
      { label: copy.season.closures, value: '60', tone: 'closed' },
      { label: copy.season.delays, value: '26', tone: 'delayed' },
      // No school was remote: that row is left out, not given as 0.
      { label: copy.season.earlyDismissals, value: '1', tone: 'earlyDismissal' },
      // Jan 12 and Jan 13 tie at 36 schools: the first of them.
      {
        label: copy.season.busiestDay,
        value: `${format.day('2026-01-12')} · ${format.schools(36)}`,
        tone: null,
      },
    ]);
  });

  it('is left out until a day has an affected school, or when there is no file', () => {
    expect(seasonSection({ ...SEASON, days: [], states: [], schools: 0, districts: 0 })).toBeNull();
    expect(seasonSection(null)).toBeNull();
  });
});

describe('recordTable', () => {
  it('gives each chance of no school a row, and each lead that gave one a column', () => {
    const table = recordTable(RECORD);
    expect(table?.title).toBe(copy.nav.trackRecord);
    expect(table?.note).toBe(format.span('2025-12-01', '2026-01-13'));
    expect(table?.caption).toBe(copy.trackRecord.caption);
    // Two days ahead gave no chance of no school: no column for it.
    expect(table?.columns).toEqual([copy.trackRecord.chanceGiven, format.lead(0), format.lead(1)]);
    expect(table?.rows).toEqual([
      { label: format.percentRange(0, 10), cells: [format.outOf(1, 40), format.outOf(2, 38)] },
      { label: format.percentRange(10, 20), cells: [format.outOf(2, 12), null] },
      { label: format.percentRange(20, 30), cells: [null, format.outOf(3, 6)] },
      { label: format.percentRange(90, 100), cells: [format.outOf(4, 4), null] },
    ]);
  });

  it('is left out until a day is scored for no school', () => {
    expect(recordTable(null)).toBeNull();
    expect(recordTable({ ...RECORD, first_day: null, last_day: null, leads: [] })).toBeNull();
    const delaysOnly = { ...RECORD, leads: RECORD.leads.slice(2) };
    expect(recordTable(delaysOnly)).toBeNull();
  });
});

describe('mapSection', () => {
  it('counts the schools and districts on the map', () => {
    expect(mapSection({ generated_on: '2026-09-25', schools: 118_132, districts: 18_227 })).toEqual(
      {
        title: copy.menu.onMap,
        note: null,
        rows: [
          { label: copy.menu.schools, value: '118,132', tone: null },
          { label: copy.menu.districts, value: '18,227', tone: null },
        ],
      },
    );
  });

  it('is left out without a directory, or with an empty one', () => {
    expect(mapSection(null)).toBeNull();
    expect(mapSection({ generated_on: '2026-09-25', schools: 0, districts: 0 })).toBeNull();
  });
});

describe('readMenu', () => {
  const INDEX = {
    schema_version: 1,
    directory: { generated_on: '2026-09-25', schools: 3, districts: 1 },
    shards: 1,
    first_ids: ['010000500870'],
    files: ['0.0123456789.json'],
  };

  function respond(files: Record<string, unknown>) {
    return vi.fn((url: string) => {
      const path = url.slice(ROOT.length);
      const body = files[path];
      return Promise.resolve(
        body === undefined
          ? new Response('', { status: 404 })
          : new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } }),
      );
    });
  }

  it('reads the three files this build ships, each as published', async () => {
    const files = createDataFiles(
      ['stats/season.json', 'track-record.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    const fetch = respond({
      'stats/season.json': SEASON,
      'track-record.json': RECORD,
      'schools/details/index.0123456789.json': INDEX,
    });
    const view = await readMenu(files, fetch);
    expect(view.season?.rows[0]?.value).toBe('51');
    expect(view.record?.rows).toHaveLength(4);
    expect(view.map?.rows.map((row) => row.value)).toEqual(['3', '1']);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('asks for nothing this build does not ship, and shows About alone', async () => {
    const fetch = respond({});
    const view = await readMenu(createDataFiles([], ROOT), fetch);
    expect(view).toEqual({ season: null, record: null, map: null });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('leaves out a part whose file cannot be read or breaks its rules', async () => {
    const files = createDataFiles(
      ['stats/season.json', 'track-record.json', 'schools/details/index.json'],
      ROOT,
    );
    const fetch = respond({
      // The days add to more than the states: a count that disagrees with its parts.
      'stats/season.json': { ...SEASON, states: [['IA', 1, 0, 0, 0]] },
      'schools/details/index.json': INDEX,
    });
    const view = await readMenu(files, fetch);
    expect(view.season).toBeNull();
    expect(view.record).toBeNull();
    expect(view.map).not.toBeNull();
  });

  it('shows About alone when every read fails', async () => {
    const files = createDataFiles(['stats/season.json', 'schools/details/index.json'], ROOT);
    const fetch = vi.fn(() => Promise.reject(new TypeError('offline')));
    expect(await readMenu(files, fetch)).toEqual({ season: null, record: null, map: null });
  });
});

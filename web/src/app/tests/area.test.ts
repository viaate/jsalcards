/**
 * The area a ZIP code opens, from made-up area, school, closings and
 * predictions files: the storm, its chances and its closings are invented for
 * these tests.
 *
 * Monday Jan 12, 2026, 9:05 PM in Kansas City. Tuesday: Kansas City 33 gives
 * 64%, Center 31%, Shawnee Mission no weather threat. One Kansas City school and a
 * private school canceled Tuesday; another private school says nothing.
 */
import { describe, expect, it, vi } from 'vitest';

import { format } from '../../copy-format';
import type { AreaRecord, AreaSource } from '../../data/areas';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles } from '../../data/files';
import type { ClosingsFile, DirectoryStamp, PredictionsFile } from '../../types/generated';
import { areaBounds, areaView, watchArea } from '../area';
import type { AreaInput } from '../area';

const ZONE = 'America/Chicago';
const NOW = new Date('2026-01-13T03:05:00Z');
const STAMP: DirectoryStamp = { generated_on: '2026-01-05', schools: 7, districts: 3 };
const DISTRICTS = [
  { index: 0, id: '2916400', name: 'KANSAS CITY 33' },
  { index: 1, id: '2908250', name: 'CENTER 58' },
  { index: 2, id: '2011640', name: 'Shawnee Mission Pub Sch' },
] as const;

function school(
  index: number,
  id: string,
  name: string,
  district: number | null,
  enrollment: number | null,
  city = 'KANSAS CITY',
): SchoolRecord {
  return {
    id,
    index,
    name,
    private: district === null,
    charter: false,
    virtual: false,
    district: district === null ? null : (DISTRICTS[district] ?? null),
    street: null,
    city,
    state: 'MO',
    zip: '64111',
    county: 'Jackson County',
    grades: { low: 'KG', high: '05' },
    enrollment,
    phone: null,
    nearby: [],
    directory: STAMP,
  };
}

const SCHOOLS: readonly SchoolRecord[] = [
  school(0, '291640000001', 'ALPHA EL', 0, 400),
  school(1, '291640000002', 'BETA EL', 0, 600),
  school(2, '290825000003', 'GAMMA EL', 1, 500),
  school(3, 'A0000001', 'DELTA ACADEMY', null, 200),
  school(4, 'A0000002', 'EPSILON SCHOOL', null, 100, 'MISSION'),
  school(5, '291640000006', 'ZETA EL', 0, 300),
  school(6, '201164000007', 'ETA EL', 2, 250, 'MISSION'),
];

/** Five schools of its own, and the two nearest others taken in. */
const AREA: AreaRecord = {
  zip: '64111',
  lon: -94.594,
  lat: 39.057,
  states: ['MO'],
  own: SCHOOLS.slice(0, 5).map((record, i) => ({
    index: record.index,
    id: record.id,
    metres: 200 + i * 100,
    lon: -94.59 - i * 0.001,
    lat: 39.05 + i * 0.001,
  })),
  near: [
    { index: 5, id: '291640000006', metres: 1500, lon: -94.6, lat: 39.06 },
    { index: 6, id: '201164000007', metres: 3000, lon: -94.62, lat: 39.04 },
  ],
  directory: STAMP,
};

const RECORDS = new Map(SCHOOLS.map((record) => [record.id, record]));

/** Tuesday's closings, posted Monday evening: Zeta (Kansas City 33) and Delta (private). */
const CLOSINGS: ClosingsFile = {
  schema_version: 1,
  generated_at: '2026-01-13T03:00:00Z',
  directory: STAMP,
  days: [
    {
      day: '2026-01-13',
      gaps: [3, 1],
      statuses: [0, 0],
      announced: [30, 20],
      reasons: [0, 0],
      shifts: [],
      clocks: [],
    },
  ],
};

function forecast(chance: number): unknown {
  return {
    state: 'forecast',
    p_no_school: chance,
    p_delay: 0.1,
    reasons: [0],
    previous: null,
    announces_at: '2026-01-13T11:30:00Z',
    buses_at: '2026-01-13T13:00:00Z',
    hours: {
      kind: 'snow_total',
      start: '2026-01-13T03:00:00Z',
      values: [0, 0.2, 0.6, 1.1, 1.8, 3.3, 4.8, 6.3, 7.1, 7.5, 7.5],
      low: 6,
      high: 9,
      heavy: { first: 5, last: 7 },
    },
    why: { base: { kind: 'similar_days', points: Math.round(chance * 100) }, reasons: [] },
    record: null,
    events: [],
  };
}

const PREDICTIONS = {
  schema_version: 1,
  generated_at: '2026-01-13T03:00:00Z',
  directory: STAMP,
  days: ['2026-01-12', '2026-01-13'],
  districts: [
    {
      district: 0,
      time_zone: ZONE,
      neighbors: [1],
      days: [{ state: 'no_threat' }, forecast(0.64)],
    },
    {
      district: 1,
      time_zone: ZONE,
      neighbors: [0],
      days: [{ state: 'no_threat' }, forecast(0.31)],
    },
    {
      district: 2,
      time_zone: ZONE,
      neighbors: [],
      days: [{ state: 'no_threat' }, { state: 'no_threat' }],
    },
  ],
} as unknown as PredictionsFile;

function input(overrides: Partial<AreaInput> = {}): AreaInput {
  return {
    zip: '64111',
    hint: null,
    area: AREA,
    records: RECORDS,
    settled: true,
    live: { closings: CLOSINGS, covered: null, predictions: PREDICTIONS },
    shipped: true,
    now: NOW,
    timeZone: ZONE,
    ...overrides,
  };
}

describe('the area panel’s view', () => {
  it('lists the ZIP code’s schools, nearest first, then the others taken in, each with its kind and distance', () => {
    const view = areaView(input());
    expect(view).not.toBeNull();
    if (view === null) return;
    expect(view.label).toBe('Schools around 64111');
    expect(view.back).toBe('Back to 64111');
    // Four of its five schools say Kansas City: more than half.
    expect(view.place).toBe('Kansas City, MO');
    expect(view.heading).toBe('5 schools');
    expect(view.own.map((row) => row.name)).toEqual([
      'Alpha Elementary',
      'Beta Elementary',
      'Gamma Elementary',
      'Delta Academy',
      'Epsilon School',
    ]);
    expect(view.own[0]).toMatchObject({
      id: '291640000001',
      kind: `Public school · ${format.grades('KG', '05')}`,
      distance: format.miles(200),
      tone: null,
    });
    expect(view.own[3]?.kind).toMatch(/^Private school/u);
    expect(view.nearHeading).toBe('2 more within 2 miles');
    expect(view.near.map((row) => row.id)).toEqual(['291640000006', '201164000007']);
    expect(view.noneNear).toBeNull();
    expect(view.loading).toBe(false);
    // The map takes in the ZIP code's point and every school of its area.
    expect(areaBounds(AREA)).toEqual([-94.62, 39.04, -94.59, 39.06]);
  });

  it('heads the chance with the students’ average over the counted schools, closed as 100% and no weather threat as 0', () => {
    const chance = areaView(input())?.chance;
    expect(chance).not.toBeNull();
    if (chance === null || chance === undefined) return;
    // (400 + 600) × 64% + 500 × 31% + 300 × 100% + 200 × 100% + 250 × 0, over 2,250 students:
    // Shawnee Mission's school counts, with no weather threat, as no chance at all.
    const mean = (1000 * 0.64 + 500 * 0.31 + 300 + 200 + 250 * 0) / 2250;
    expect(chance.number).toBe(String(Math.round(mean * 100)));
    expect(chance.number).toBe('58');
    expect(chance.meaning).toBe('Chance of no school Tuesday');
    expect(chance.day).toBe('2026-01-13');
    expect(chance.why.map(({ number, text }) => `${number} ${text}`)).toEqual([
      '64% Kansas City 33 decides for 2 schools here.',
      '31% Center 58 decides for 1 school here.',
      '100% Kansas City 33 canceled Tuesday at 1 school here.',
      '0% Shawnee Mission Public Schools has no weather threat Tuesday at 1 school here.',
      '100% Delta Academy canceled Tuesday.',
    ]);
    // Epsilon says nothing and is outside a district.
    expect(chance.left).toBe(
      '1 of the 7 schools here has no chance given for Tuesday and is left out.',
    );
    // The night ahead, as Kansas City 33 has it; its usual announcement is its own, so left off.
    expect(chance.chart?.kind).toBe('snow_total');
    expect(chance.chartOf).toBe('Kansas City 33’s forecast');
    expect(chance.chart?.announces).toBeNull();
    expect(chance.chart?.key.some((row) => row.mark === 'announces')).toBe(false);
    expect(chance.announces(NOW)).toBeNull();
  });

  it('keeps the usual announcement on the chart where one district alone decides by chance', () => {
    const one = { ...AREA, own: AREA.own.slice(0, 2), near: [] };
    const chance = areaView(input({ area: one }))?.chance;
    expect(chance?.number).toBe('64');
    expect(chance?.why.map(({ text }) => text)).toEqual([
      'Kansas City 33 decides for both schools here.',
    ]);
    expect(chance?.left).toBeNull();
    // Its own forecast, and no other: nothing to say whose it is.
    expect(chance?.chartOf).toBeNull();
    expect(chance?.chart?.key.some((row) => row.mark === 'announces')).toBe(true);
    expect(chance?.announces(NOW)).not.toBeNull();
  });

  it('leaves out a school with no student count, as it weighs nothing, and says so', () => {
    const records = new Map(RECORDS);
    // Gamma (Center 58) and Delta (canceled) give no student count.
    records.set('290825000003', school(2, '290825000003', 'GAMMA EL', 1, null));
    records.set('A0000001', school(3, 'A0000001', 'DELTA ACADEMY', null, 0));
    const chance = areaView(input({ records }))?.chance;
    // (400 + 600) × 64% + 300 × 100% + 250 × 0, over 1,550 students.
    const mean = (1000 * 0.64 + 300 + 250 * 0) / 1550;
    expect(chance?.number).toBe(String(Math.round(mean * 100)));
    expect(chance?.why.map(({ number, text }) => `${number} ${text}`)).toEqual([
      '64% Kansas City 33 decides for 2 schools here.',
      '100% Kansas City 33 canceled Tuesday at 1 school here.',
      '0% Shawnee Mission Public Schools has no weather threat Tuesday at 1 school here.',
    ]);
    expect(chance?.left).toBe(
      '3 of the 7 schools here are left out: 1 has no chance given for Tuesday and 2 have no student count.',
    );
    // Without Epsilon, which has no chance given: only the ones with no student count.
    const given = { ...AREA, own: AREA.own.slice(0, 4) };
    expect(areaView(input({ area: given, records }))?.chance?.left).toBe(
      '2 of the 6 schools here have no student count and are left out.',
    );
    // No student count anywhere a chance is given: nothing to weigh, so no chance.
    const unweighed = new Map(
      [...RECORDS].map(([id, record]) => [id, { ...record, enrollment: null }]),
    );
    expect(areaView(input({ records: unweighed }))?.chance).toBeNull();
  });

  it('shows no chance without a predictions file, nor from statuses alone', () => {
    expect(areaView(input({ shipped: false }))?.chance).toBeNull();
    const none = { closings: CLOSINGS, covered: null, predictions: null };
    expect(areaView(input({ live: none }))?.chance).toBeNull();
    // Only the schools that posted: a chance is given for none of them.
    const posted = {
      ...AREA,
      own: AREA.own.slice(3, 4),
      near: AREA.near.slice(0, 1),
    };
    expect(areaView(input({ area: posted }))?.chance).toBeNull();
    // No weather threat anywhere in the area: no chance, not even one under 1%.
    const clear = { ...AREA, own: [], near: AREA.near.slice(1) };
    expect(areaView(input({ area: clear }))?.chance).toBeNull();
    // Once Tuesday's buses have run, nothing is left to give a chance for.
    expect(areaView(input({ now: new Date('2026-01-13T13:30:00Z') }))?.chance).toBeNull();
  });

  it('keeps the list’s shape while it reads, then lists the schools read, says how many are not, and gives no chance', () => {
    const records = new Map<string, SchoolRecord | null>(RECORDS);
    records.set('291640000002', null);
    const view = areaView(input({ records, settled: false }));
    expect(view).toMatchObject({ loading: true, chance: null, own: [], near: [], heading: '' });
    expect(view?.place).toBe('Kansas City, MO');
    // Reading is done: the schools read, under the area's own counts, and the one that is not.
    const read = areaView(input({ records }));
    expect(read).toMatchObject({
      loading: false,
      chance: null,
      heading: '5 schools',
      nearHeading: '2 more within 2 miles',
      unread: '1 school did not load',
    });
    expect(read?.own.map((row) => row.id)).not.toContain('291640000002');
    expect(read?.own).toHaveLength(4);
    expect(read?.near).toHaveLength(2);
    expect(areaView(input())?.unread).toBeNull();
    // A record from another directory is not the school the file names.
    const stale = new Map(RECORDS);
    stale.set('291640000001', {
      ...SCHOOLS[0],
      directory: { ...STAMP, schools: 8 },
    } as SchoolRecord);
    expect(areaView(input({ records: stale, settled: false }))?.loading).toBe(true);
    expect(areaView(input({ records: stale }))).toMatchObject({
      loading: false,
      chance: null,
      unread: '1 school did not load',
    });
  });

  it('lights each school with today’s status, and counts them over the list', () => {
    const today: ClosingsFile = {
      ...CLOSINGS,
      generated_at: '2026-01-12T12:30:00Z',
      days: [
        {
          day: '2026-01-12',
          gaps: [0, 1, 2],
          statuses: [0, 2, 0],
          announced: [30, 20, 10],
          reasons: [0, 0, 0],
          shifts: [],
          clocks: [],
        },
      ],
    };
    const view = areaView(
      input({
        live: { closings: today, covered: null, predictions: null },
        now: new Date('2026-01-12T12:45:00Z'),
      }),
    );
    expect([...(view?.own ?? []), ...(view?.near ?? [])].map((row) => row.tone)).toEqual([
      'closed',
      null,
      'remote',
      null,
      null,
      'closed',
      null,
    ]);
    expect(view?.counts).toEqual([
      { status: 'closed', text: '2 closed' },
      { status: 'remote', text: '1 remote' },
    ]);
    expect(
      areaView(input({ live: { closings: null, covered: null, predictions: null } }))?.counts,
    ).toEqual([]);
  });

  it('says plainly when the nearest others are taken in, or none are near', () => {
    const sparse = { ...AREA, own: AREA.own.slice(3, 5), near: AREA.own.slice(0, 2) };
    const view = areaView(input({ area: sparse }));
    expect(view?.heading).toBe('2 schools');
    expect(view?.nearHeading).toBe('2 more within 2 miles');
    expect(view?.near.map((row) => row.id)).toEqual(['291640000001', '291640000002']);
    expect(view?.noneNear).toBeNull();
    // Half of its own schools say Kansas City, not more: its state instead.
    expect(view?.place).toBe('Missouri');
    const alone = areaView(input({ area: { ...sparse, near: [] } }));
    expect(alone?.nearHeading).toBeNull();
    expect(alone?.noneNear).toBe('No others within 2 miles');
    const empty = areaView(input({ area: { ...sparse, own: [], near: [] } }));
    expect(empty?.heading).toBe('No schools');
    expect(empty?.noneNear).toBe('None within 2 miles');
    expect(areaBounds({ ...sparse, own: [], near: [] })).toEqual([
      -94.594, 39.057, -94.594, 39.057,
    ]);
  });

  it('shows the ZIP code and what search knew while it reads, and nothing for a ZIP code with no area', () => {
    const reading = areaView(
      input({ area: null, records: null, settled: false, hint: { zip: '64111', sub: 'Missouri' } }),
    );
    expect(reading).toMatchObject({ zip: '64111', place: 'Missouri', loading: true, own: [] });
    expect(areaView(input({ area: null, records: null, settled: true }))).toBeNull();
  });
});

describe('watching an area', () => {
  const files = createDataFiles(
    ['predictions/latest.json', 'live/closings.json'],
    'https://snow.test/data/',
  );

  it('reads the area, its schools and the live files, and shows each step', async () => {
    const areas: AreaSource = { shipped: true, get: vi.fn(() => Promise.resolve(AREA)) };
    const get = vi.fn((id: string) => Promise.resolve(RECORDS.get(id) ?? null));
    const details: DetailsSource = { get };
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation((url) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              (url instanceof Request ? url.url : url.toString()).includes('predictions')
                ? PREDICTIONS
                : CLOSINGS,
            ),
          ),
        ),
      );
    const views: ReturnType<typeof areaView>[] = [];
    const stop = watchArea({
      files,
      areas,
      details,
      zip: '64111',
      hint: { zip: '64111', sub: 'Missouri' },
      onView: (view) => views.push(view),
      now: () => NOW,
      timeZone: () => ZONE,
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
    });
    stop();
    fetchSpy.mockRestore();
    expect(views[0]).toMatchObject({ loading: true, place: 'Missouri' });
    expect(views.at(-1)?.chance?.number).toBe('58');
    expect(get).toHaveBeenCalledTimes(7);
  });

  it('reads again, with the live files, an area or a school that could not be read', async () => {
    let areaReads = 0;
    const getArea = vi.fn(() => Promise.resolve(++areaReads === 1 ? null : AREA));
    const areas: AreaSource = { shipped: true, get: getArea };
    let betaReads = 0;
    const get = vi.fn((id: string) =>
      Promise.resolve(
        id === '291640000002' && ++betaReads === 1 ? null : (RECORDS.get(id) ?? null),
      ),
    );
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(new Response('{}', { status: 503 })));
    const views: ReturnType<typeof areaView>[] = [];
    const stop = watchArea({
      files,
      areas,
      details: { get },
      zip: '64111',
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOW,
      timeZone: () => ZONE,
      pollMs: 10,
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.unread === null && views.at(-1)?.loading === false).toBe(true);
    });
    stop();
    fetchSpy.mockRestore();
    // Nothing at first, as the area could not be read; then the list short of Beta; then all of it.
    expect(views).toContain(null);
    expect(views.some((view) => view?.unread === '1 school did not load')).toBe(true);
    expect(views.at(-1)?.own).toHaveLength(5);
    expect(getArea).toHaveBeenCalledTimes(2);
    // Only the school missed is read again.
    expect(get.mock.calls.filter(([id]) => id === '291640000002')).toHaveLength(2);
    expect(get).toHaveBeenCalledTimes(8);
  });

  it('shows nothing where the build ships no areas, or the ZIP code has none', async () => {
    const get = vi.fn(() => Promise.resolve(null));
    const details: DetailsSource = { get };
    const none: ReturnType<typeof areaView>[] = [];
    watchArea({
      files,
      areas: { shipped: false, get: () => Promise.resolve(null) },
      details,
      zip: '64111',
      hint: null,
      onView: (view) => none.push(view),
    })();
    expect(none).toEqual([null]);
    const missing: ReturnType<typeof areaView>[] = [];
    const stop = watchArea({
      files: createDataFiles([], 'https://snow.test/data/'),
      areas: { shipped: true, get: () => Promise.resolve(null) },
      details,
      zip: '00000',
      hint: null,
      onView: (view) => missing.push(view),
    });
    await vi.waitFor(() => {
      expect(missing.at(-1)).toBeNull();
    });
    stop();
    expect(get).not.toHaveBeenCalled();
  });
});

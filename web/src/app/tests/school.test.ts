import { afterEach, describe, expect, it, vi } from 'vitest';

import { copy, format } from '../../copy';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles } from '../../data/files';
import { NO_STATUS } from '../../data/school-day';
import type { DayOutlook, StatusRow } from '../../data/school-day';
import { createDirectory, parsePoints } from '../../data/directory';
import {
  jsonResponse,
  testClosings,
  testDay,
  testMeta,
  testPoints,
} from '../../data/tests/builders';
import { schoolView, watchSchool } from '../school';
import type { SchoolView, ViewInput } from '../school';

/** How long a test waits for code loaded on demand, on a busy machine. */
const WAIT = { timeout: 4_000 };
const NBSP = ' ';
const ROOT = 'https://snow.test/data/';
const STAMP = { generated_on: '2026-01-05', schools: 3, districts: 1 };
/** Noon in Kansas City, 18:00 UTC on Jan 12: the same day everywhere in the contiguous US. */
const NOON = new Date('2026-01-12T18:00:00Z');

/** Made up for these tests, in the shape the detail files give. */
const PRIVATE: SchoolRecord = {
  id: 'ZZ000001',
  index: 2,
  name: 'THE TEST HILL SCHOOL - NORTH CAMPUS',
  private: true,
  charter: false,
  virtual: false,
  district: null,
  street: '400 W 51ST ST',
  city: 'KANSAS CITY',
  state: 'MO',
  zip: '64112',
  county: 'Jackson County',
  grades: { low: 'PK', high: '12' },
  enrollment: 1174,
  phone: '8165550100',
  nearby: [
    {
      index: 0,
      id: 'ZZ000003',
      name: 'VISITATION TEST SCHOOL',
      metres: 444,
      lon: -94.588871,
      lat: 39.03368,
    },
    { index: 1, id: 'ZZ000004', name: "ST TEST'S ACADEMY", metres: 1186, lon: -94.59, lat: 39.02 },
  ],
  directory: STAMP,
};
const PUBLIC: SchoolRecord = {
  ...PRIVATE,
  id: '290000199999',
  index: 0,
  name: 'BELLE ELEM.',
  private: false,
  district: { index: 0, id: '2999999', name: 'MARIES CO. R-II' },
  street: null,
  zip: null,
  county: null,
  grades: { low: 'KG', high: '04' },
  enrollment: 0,
  phone: null,
};

function input(overrides: Partial<ViewInput> = {}): ViewInput {
  return {
    id: PRIVATE.id,
    hint: null,
    record: PRIVATE,
    settled: true,
    status: NO_STATUS,
    outlook: 'not_enough_data',
    now: NOON,
    timeZone: 'America/Chicago',
    ...overrides,
  };
}

describe('schoolView', () => {
  it('names the school as the map does, its campus on a line of its own, and what it is', () => {
    const view = schoolView(input());
    expect(view).toMatchObject({
      id: 'ZZ000001',
      name: 'The Test Hill School',
      campus: 'North Campus',
      kind: `${copy.detail.privateSchool} · PK–12`,
      place: 'Kansas City, MO · Jackson County',
      status: [],
      // No history gives a chance: no chance card at all.
      outlook: null,
      loading: false,
    });
    expect(view?.facts).toEqual([
      { label: copy.detail.students, lines: ['1,174'], href: null },
      {
        label: copy.detail.address,
        lines: ['400 W 51st St', 'Kansas City, MO 64112'],
        href: null,
      },
      { label: copy.detail.phone, lines: [`(816)${NBSP}555-0100`], href: 'tel:+18165550100' },
    ]);
    // The nearest schools, named as the map names them, with how far each is.
    expect(view?.nearby).toEqual([
      {
        id: 'ZZ000003',
        name: 'Visitation Test School',
        distance: `0.3${NBSP}mi`,
        tone: null,
        lon: -94.588871,
        lat: 39.03368,
      },
      {
        id: 'ZZ000004',
        name: "St Test's Academy",
        distance: `0.7${NBSP}mi`,
        tone: null,
        lon: -94.59,
        lat: 39.02,
      },
    ]);
  });

  it('keys each nearby school with its status today, where the live file states one', () => {
    const meta = testMeta([
      { id: 'ZZ000003', name: 'A', lon: 0, lat: 0, district: -1 },
      { id: 'ZZ000004', name: 'B', lon: 0, lat: 0, district: -1 },
      { id: 'ZZ000001', name: 'C', lon: 0, lat: 0, district: -1 },
    ]);
    const closings = testClosings('2026-01-12T17:40:00Z', meta, [testDay('2026-01-12', [[1, 2]])]);
    const view = schoolView(
      input({ record: { ...PRIVATE, directory: closings.directory }, closings }),
    );
    expect(view?.nearby.map((near) => near.tone)).toEqual([null, 'remote']);
  });

  it('gives a public school its district, and leaves out what NCES does not give', () => {
    const view = schoolView(input({ id: PUBLIC.id, record: PUBLIC }));
    expect(view).toMatchObject({
      name: 'Belle Elementary',
      campus: null,
      kind: `${copy.detail.publicSchool} · K–4`,
      place: 'Kansas City, MO',
    });
    // No students (NCES reports none), no street, no phone: those rows are left out.
    expect(view?.facts).toEqual([
      { label: copy.detail.district, lines: ['Maries County R-II'], href: null },
      { label: copy.detail.address, lines: ['Kansas City, MO'], href: null },
    ]);
    expect(schoolView(input({ record: { ...PRIVATE, private: false, charter: true } }))?.kind).toBe(
      `${copy.detail.charterSchool} · PK–12`,
    );
    expect(schoolView(input({ record: { ...PRIVATE, grades: null } }))?.kind).toBe(
      copy.detail.privateSchool,
    );
  });

  it('names a district by what NCES shortened, its Pub Sch as the Public Schools it is', () => {
    const record: SchoolRecord = {
      ...PUBLIC,
      district: { index: 0, id: '2011640', name: 'Shawnee Mission Pub Sch' },
    };
    expect(schoolView(input({ id: PUBLIC.id, record }))?.facts[0]).toEqual({
      label: copy.detail.district,
      lines: ['Shawnee Mission Public Schools'],
      href: null,
    });
  });

  it('shows what a pick knew until the record is read, and nothing for an id with no school', () => {
    const hint = {
      id: PRIVATE.id,
      name: 'The Test Hill School - North Campus',
      sub: 'Kansas City, MO',
    };
    expect(schoolView(input({ hint, record: null, settled: false }))).toEqual({
      id: PRIVATE.id,
      name: 'The Test Hill School',
      campus: 'North Campus',
      kind: null,
      place: 'Kansas City, MO',
      status: [],
      outlook: null,
      chance: null,
      facts: [],
      nearby: [],
      loading: true,
    });
    expect(schoolView(input({ record: null, settled: false }))).toMatchObject({
      name: '',
      loading: true,
    });
    expect(schoolView(input({ record: null, settled: true }))).toBeNull();
    // A hint for another school is not this one's.
    expect(
      schoolView(input({ hint: { ...hint, id: PUBLIC.id }, record: null, settled: true })),
    ).toBeNull();
  });

  it('writes the status lines today first, with what the row states', () => {
    const view = schoolView(
      input({
        status: {
          today: {
            status: 1,
            reason: 1,
            announcedAt: new Date('2026-01-12T11:12:00Z'),
            shiftMinutes: 120,
            clockMinute: 600,
          },
          tomorrow: {
            status: 0,
            reason: null,
            announcedAt: null,
            shiftMinutes: null,
            clockMinute: null,
          },
        },
      }),
    );
    expect(view?.status).toEqual([
      {
        tone: 'delayed',
        headline: copy.statusLine.delayed.today,
        detail: format.delay(120, 600),
        note: `${copy.reason.ice} · ${format.posted(new Date('2026-01-12T11:12:00Z'), 'America/Chicago', NOON)}`,
      },
      { tone: 'closed', headline: copy.statusLine.closed.tomorrow, detail: null, note: null },
    ]);
    expect(schoolView(input({ status: { today: 'open', tomorrow: null } }))?.status).toEqual([
      { tone: 'open', headline: copy.open.today, detail: null, note: null },
    ]);
  });

  it('gives each day’s chance where the district has one, and one line where it does not', () => {
    const view = schoolView(
      input({
        outlook: {
          today: { state: 'forecast', noSchool: 0.34, delay: 0.12, reasons: [0, 2] },
          tomorrow: { state: 'no_threat' },
        },
      }),
    );
    expect(view?.outlook).toEqual([
      {
        label: copy.days.today,
        chance: '34%',
        line: copy.predictions.noSchool,
        delay: `${copy.predictions.delay} 12%`,
        reasons: `${copy.reason.winterStorm} · ${copy.reason.extremeCold}`,
        share: 0.34,
      },
      {
        label: copy.days.tomorrow,
        chance: null,
        line: copy.empty.noThreat,
        delay: null,
        reasons: null,
        share: null,
      },
    ]);
    expect(schoolView(input({ outlook: null }))?.outlook).toBeNull();
  });

  it('leaves out a day with no history to give a chance, and the card with no day left', () => {
    const forecast: DayOutlook = { state: 'forecast', noSchool: 0.34, delay: 0.12, reasons: [] };
    const none: DayOutlook = { state: 'not_enough_data' };
    expect(
      schoolView(input({ outlook: { today: forecast, tomorrow: none } }))?.outlook?.map((day) => [
        day.label,
        day.chance,
      ]),
    ).toEqual([[copy.days.today, '34%']]);
    expect(
      schoolView(input({ outlook: { today: none, tomorrow: forecast } }))?.outlook?.map((day) => [
        day.label,
        day.chance,
      ]),
    ).toEqual([[copy.days.tomorrow, '34%']]);
    expect(schoolView(input({ outlook: { today: none, tomorrow: none } }))?.outlook).toBeNull();
    expect(schoolView(input({ outlook: { today: none, tomorrow: null } }))?.outlook).toBeNull();
    expect(schoolView(input({ outlook: 'not_enough_data' }))?.outlook).toBeNull();
  });

  it('leaves a day’s chance out beside that day’s status: the fact beats the forecast', () => {
    const today: DayOutlook = { state: 'forecast', noSchool: 0.97, delay: 0.02, reasons: [0] };
    const tomorrow: DayOutlook = { state: 'forecast', noSchool: 0.4, delay: 0.2, reasons: [] };
    const closed: StatusRow = {
      status: 0,
      reason: 0,
      announcedAt: null,
      shiftMinutes: null,
      clockMinute: null,
    };
    const view = schoolView(
      input({ status: { today: closed, tomorrow: null }, outlook: { today, tomorrow } }),
    );
    expect(view?.status.map((line) => line.headline)).toEqual([copy.statusLine.closed.today]);
    expect(view?.outlook).toEqual([
      {
        label: copy.days.tomorrow,
        chance: '40%',
        line: copy.predictions.noSchool,
        delay: `${copy.predictions.delay} 20%`,
        reasons: null,
        share: 0.4,
      },
    ]);
    // "Open today" decides nothing: no closing is posted yet, and on a storm morning the chance
    // is what warns. It stays, beside the open line.
    const open = schoolView(
      input({ status: { today: 'open', tomorrow: null }, outlook: { today, tomorrow } }),
    );
    expect(open?.status.map((line) => line.headline)).toEqual([copy.open.today]);
    expect(open?.outlook).toMatchObject([
      { label: copy.days.today, chance: '97%' },
      { label: copy.days.tomorrow, chance: '40%' },
    ]);
    // A file that stops at today leaves no chance to give: no outlook at all.
    expect(
      schoolView(
        input({ status: { today: closed, tomorrow: null }, outlook: { today, tomorrow: null } }),
      )?.outlook,
    ).toBeNull();
    // Tomorrow's status known, as a district that announced it the night before: today's alone.
    expect(
      schoolView(input({ status: { today: null, tomorrow: closed }, outlook: { today, tomorrow } }))
        ?.outlook,
    ).toEqual([
      {
        label: copy.days.today,
        chance: '97%',
        line: copy.predictions.noSchool,
        delay: `${copy.predictions.delay} 2%`,
        reasons: copy.reason.winterStorm,
        share: 0.97,
      },
    ]);
    // Both days decided: no day left to give a chance for, and no card.
    expect(
      schoolView(
        input({ status: { today: closed, tomorrow: closed }, outlook: { today, tomorrow } }),
      )?.outlook,
    ).toBeNull();
    // Open today and closed tomorrow: today's chance alone.
    expect(
      schoolView(
        input({ status: { today: 'open', tomorrow: closed }, outlook: { today, tomorrow } }),
      )?.outlook,
    ).toMatchObject([{ label: copy.days.today, chance: '97%' }]);
    // A status the formatters refuse shows no line: today's chance stays.
    expect(
      schoolView(
        input({
          status: {
            today: { ...closed, announcedAt: new Date('2026-01-12T11:12:00Z') },
            tomorrow: null,
          },
          outlook: { today, tomorrow },
          timeZone: 'Not/A_Zone',
        }),
      ),
    ).toMatchObject({
      status: [],
      outlook: [{ label: copy.days.today }, { label: copy.days.tomorrow }],
    });
  });
});

describe('watchSchool', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function details(record: SchoolRecord | null): DetailsSource {
    return { get: vi.fn(() => Promise.resolve(record)) };
  }

  it('shows the pick’s hint at once, then the record and the day from the live files', async () => {
    const meta = testMeta([
      { id: '010000500870', name: 'A', lon: 0, lat: 0, district: 0 },
      { id: '010000500871', name: 'B', lon: 0, lat: 0, district: 0 },
      { id: 'ZZ000001', name: 'C', lon: 0, lat: 0, district: -1 },
    ]);
    const closings = testClosings('2026-01-12T17:40:00Z', meta, [testDay('2026-01-12', [[2, 0]])]);
    const files = createDataFiles(['live/closings.json'], ROOT);
    const fetchImpl = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(closings));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: details({ ...PRIVATE, directory: closings.directory }),
      id: PRIVATE.id,
      hint: { id: PRIVATE.id, name: 'The Test Hill School', sub: 'Kansas City, MO' },
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    expect(views).toHaveLength(1);
    expect(views[0]).toMatchObject({ name: 'The Test Hill School', loading: true, status: [] });
    await vi.waitFor(() => {
      expect(views).toHaveLength(2);
    }, WAIT);
    expect(views[1]).toMatchObject({
      name: 'The Test Hill School',
      loading: false,
      status: [{ tone: 'closed', headline: copy.statusLine.closed.today }],
      // The build ships no predictions: no history gives a chance, and there is no chance card.
      outlook: null,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    stop();
    fetchImpl.mockRestore();
  });

  it('says there is no such school once the record is not found, and reads nothing it need not', async () => {
    const fetchImpl = vi.spyOn(globalThis, 'fetch');
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files: createDataFiles([], ROOT),
      details: details(null),
      id: 'ZZ000002',
      hint: null,
      onView: (view) => views.push(view),
    });
    // The build ships no records and the pick knew nothing: no panel, not even for a moment.
    expect(views).toEqual([null]);
    expect(fetchImpl).not.toHaveBeenCalled();
    stop();

    const shipped = createDataFiles(['schools/details/index.0123456789.json'], ROOT);
    const stopShipped = watchSchool({
      files: shipped,
      details: details(null),
      id: 'ZZ000002',
      hint: null,
      onView: (view) => views.push(view),
    });
    await vi.waitFor(() => {
      expect(views).toHaveLength(3);
    }, WAIT);
    // Its shape while the record is read, then nothing: the directory has no such school.
    expect(views[1]).toMatchObject({ name: '', loading: true });
    expect(views[2]).toBeNull();
    expect(fetchImpl).not.toHaveBeenCalled();
    stopShipped();
    fetchImpl.mockRestore();
  });

  it('reads the live files again while open, and stops when asked', async () => {
    vi.useFakeTimers();
    const files = createDataFiles(
      ['live/closings.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse({})));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: details(PRIVATE),
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      pollMs: 1000,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const shown = views.length;
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(views).toHaveLength(shown);
    fetchImpl.mockRestore();
  });
});

describe('the chance section in the panel', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  /** Three schools: the panel's (district 0), and one in each of two districts next door. */
  const meta = testMeta(
    [
      { id: '290000199999', name: 'BELLE ELEM.', lon: -94.6, lat: 39, district: 0 },
      { id: '290000299999', name: 'NEXT DOOR ELEM.', lon: -94.5, lat: 39, district: 1 },
      { id: '290000399999', name: 'OTHER SIDE ELEM.', lon: -94.7, lat: 39, district: 2 },
    ],
    ['2999999', '2900002', '2900003'],
  );
  const stamp = { generated_on: meta.generated_on, schools: 3, districts: 3 };
  const record: SchoolRecord = {
    ...PUBLIC,
    index: 0,
    district: { index: 0, id: '2999999', name: 'MARIES CO. R-II' },
    directory: stamp,
  };
  /** Monday Jan 12, 2026, 9:05 PM in Kansas City. */
  const evening = new Date('2026-01-13T03:05:00Z');
  const predictions = {
    schema_version: 1,
    generated_at: '2026-01-13T03:00:00Z',
    directory: stamp,
    days: ['2026-01-12', '2026-01-13'],
    districts: [
      {
        district: 0,
        neighbors: [1, 2],
        days: [
          { state: 'no_threat' },
          {
            state: 'forecast',
            p_no_school: 0.45,
            p_delay: 0.2,
            reasons: [0],
            previous: null,
            announces_at: '2026-01-13T12:00:00Z',
            buses_at: null,
            hours: null,
            why: {
              base: { kind: 'similar_days', points: 30 },
              reasons: [{ kind: 'neighbors', points: 15, districts: [1, 2], status: 0 }],
            },
            record: null,
            events: [],
          },
        ],
      },
    ],
  };
  const closings = testClosings('2026-01-13T03:00:00Z', meta, [
    {
      ...testDay('2026-01-13', [
        [1, 0],
        [2, 0],
      ]),
      announced: [20, 10],
    },
  ]);

  it('gives a public school its district’s chance, and a private school none', () => {
    const outlook = {
      today: { state: 'no_threat' } as const,
      tomorrow: {
        state: 'forecast' as const,
        noSchool: 0.45,
        delay: 0.2,
        reasons: [0 as const],
        day: '2026-01-13',
      },
    };
    const view = schoolView(input({ id: record.id, record, outlook, now: evening }));
    expect(view?.chance).toMatchObject({
      number: '45',
      meaning: 'Chance of no school Tuesday',
      delay: '20% chance of a delayed start instead',
    });
    expect(schoolView(input({ outlook, now: evening }))?.chance).toBeNull();
    // With no chance to give, the panel keeps its status and outlook cards instead.
    expect(schoolView(input({ id: record.id, record, now: evening }))?.chance).toBeNull();
  });

  it('reads the districts next door through the directory, once, and names them when it comes', async () => {
    const files = createDataFiles(
      ['live/closings.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    const fetchImpl = vi.spyOn(globalThis, 'fetch').mockImplementation((request) => {
      const url = request instanceof Request ? request.url : request.toString();
      return Promise.resolve(jsonResponse(url.includes('predictions') ? predictions : closings));
    });
    const points = parsePoints(
      testPoints(
        meta.ids.map((id, i) => ({
          id,
          name: meta.names[i] ?? '',
          lon: -94.6,
          lat: 39,
          district: i,
        })),
        3,
      ),
      meta,
    );
    if (points === null) throw new Error('no points');
    const directory = vi.fn(() => Promise.resolve(createDirectory(meta, points)));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve(record)) },
      id: record.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => evening,
      timeZone: () => 'America/Chicago',
      directory,
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.chance?.moments).toHaveLength(3);
    }, WAIT);
    const named = views.at(-1)?.chance;
    expect(named?.moments.map((moment) => moment.text)).toEqual([
      'District 2900002 canceled Tuesday',
      'District 2900003 canceled Tuesday',
      'Maries County R-II usually announces',
    ]);
    expect(named?.why?.lines.map((line) => `${line.points} ${line.lead}${line.rest}`)).toEqual([
      '+15 District 2900002 and District 2900003, next door, have already canceled.',
    ]);
    // Before the directory came, the same sum, by how many.
    const first = views.find((view) => (view?.chance ?? null) !== null)?.chance;
    expect(first?.moments.map((moment) => moment.mark)).toEqual(['next']);
    expect(first?.why?.lines[0]?.lead).toBe('2 districts next door');
    expect(directory).toHaveBeenCalledTimes(1);
    expect(directory).toHaveBeenCalledWith(stamp);
    stop();
    fetchImpl.mockRestore();
  });
});

import { afterEach, describe, expect, it, vi } from 'vitest';

import { copy, format } from '../../copy';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles } from '../../data/files';
import { NO_STATUS } from '../../data/school-day';
import type { DayOutlook, StatusRow } from '../../data/school-day';
import { jsonResponse, testClosings, testDay, testMeta } from '../../data/tests/builders';
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
      outlook: 'not_enough_data',
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

  it('leaves today’s chance out beside today’s status: the fact beats the forecast', () => {
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
    // Open today, as the live check confirmed, is today's status too.
    expect(
      schoolView(input({ status: { today: 'open', tomorrow: null }, outlook: { today, tomorrow } }))
        ?.outlook,
    ).toMatchObject([{ label: copy.days.tomorrow, chance: '40%' }]);
    // A file that stops at today leaves no chance to give: no outlook at all.
    expect(
      schoolView(
        input({ status: { today: closed, tomorrow: null }, outlook: { today, tomorrow: null } }),
      )?.outlook,
    ).toBeNull();
    // A status tomorrow alone leaves today's chance in.
    expect(
      schoolView(input({ status: { today: null, tomorrow: closed }, outlook: { today, tomorrow } }))
        ?.outlook,
    ).toMatchObject([
      { label: copy.days.today, chance: '97%' },
      { label: copy.days.tomorrow, chance: '40%' },
    ]);
    // "Not enough data" gives no chance to leave out.
    expect(
      schoolView(input({ status: { today: closed, tomorrow: null }, outlook: 'not_enough_data' }))
        ?.outlook,
    ).toBe('not_enough_data');
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
      // The build ships no predictions: no history gives a chance.
      outlook: 'not_enough_data',
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

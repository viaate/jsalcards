import { afterEach, describe, expect, it, vi } from 'vitest';

import { copy } from '../../copy';
import { format } from '../../copy-format';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDataFiles, withLiveRoot } from '../../data/files';
import { LIVE_POLL_MS, LIVE_SIDE_POLL_MS, closingsReader, startLive } from '../../data/live';
import { WAKE_CHECK_MS } from '../../state/wake';
import { NO_STATUS } from '../../data/school-day';
import type { DayOutlook, SchoolStatus, StatusRow } from '../../data/school-day';
import { createDirectory, parsePoints } from '../../data/directory';
import {
  jsonResponse,
  testClosings,
  testDay,
  testMeta,
  testPoints,
} from '../../data/tests/builders';
import { namesOf, readLiveFiles, schoolView, watchSchool } from '../school';
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
    outlook: null,
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
      // No outlook given: no chance.
      chance: null,
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
            manual: false,
          },
          tomorrow: {
            status: 0,
            reason: null,
            announcedAt: null,
            shiftMinutes: null,
            clockMinute: null,
            manual: false,
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

  it('says a status the site’s own team set is confirmed by the team, before when it was posted', () => {
    const posted = new Date('2026-01-12T12:40:00Z');
    const view = schoolView(
      input({
        status: {
          today: {
            status: 0,
            reason: null,
            announcedAt: posted,
            shiftMinutes: null,
            clockMinute: null,
            manual: true,
          },
          tomorrow: null,
        },
      }),
    );
    expect(view?.status).toEqual([
      {
        tone: 'closed',
        headline: copy.statusLine.closed.today,
        detail: null,
        note: `${copy.detail.confirmed} · ${format.posted(posted, 'America/Chicago', NOON)}`,
      },
    ]);
  });

  it('shows no chance card of its own, whatever the outlook: the chance is the section’s', () => {
    const today: DayOutlook = { state: 'forecast', noSchool: 0.97, delay: 0.02, reasons: [0] };
    const tomorrow: DayOutlook = { state: 'forecast', noSchool: 0.4, delay: 0.2, reasons: [] };
    const view = schoolView(input({ outlook: { today, tomorrow, timeZone: 'America/Chicago' } }));
    expect(view).not.toHaveProperty('outlook');
    expect(view?.chance).toBeNull();
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
      // The build ships no predictions: no chance to give.
      chance: null,
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

/** The URL a fetch was called with. */
function urlOf(input: string | URL | Request): string {
  return input instanceof Request ? input.url : input.toString();
}

describe('the live files at a live root', () => {
  const LIVE = 'https://live.snow.test/v1/';
  const meta = testMeta([
    { id: '010000500870', name: 'A', lon: 0, lat: 0, district: 0 },
    { id: '010000500871', name: 'B', lon: 0, lat: 0, district: 0 },
    { id: 'ZZ000001', name: 'C', lon: 0, lat: 0, district: -1 },
  ]);
  const newer = testClosings('2026-01-12T17:40:00Z', meta, [testDay('2026-01-12', [[2, 0]])]);
  const older = testClosings('2026-01-12T17:20:00Z', meta, []);

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('reads the closings and the chances from the root, and the other live files from the build', async () => {
    const files = withLiveRoot(
      createDataFiles(['live/closings.json', 'live/covered.json'], ROOT),
      LIVE,
    );
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const read = await readLiveFiles(files);
    expect(read.closings).toEqual(newer);
    expect(fetchImpl.mock.calls.map(([url]) => urlOf(url)).sort()).toEqual([
      `${LIVE}live/closings.json`,
      `${LIVE}predictions/latest.json`,
      `${ROOT}live/covered.json`,
    ]);
  });

  it('keeps the newer file’s status when an older file is read after it', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    const answers = [newer, older, older];
    // The root's chances are read too (no file there yet: a 404); the closings take the answers.
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation((url) =>
        Promise.resolve(
          urlOf(url).endsWith('predictions/latest.json')
            ? new Response(null, { status: 404 })
            : jsonResponse(answers.shift() ?? older),
        ),
      );
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      pollMs: 1000,
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchImpl.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(
      fetchImpl.mock.calls.every(([url]) =>
        [`${LIVE}live/closings.json`, `${LIVE}predictions/latest.json`].includes(urlOf(url)),
      ),
    ).toBe(true);
    expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
    stop();
  });

  it('never shows a file older than the one the map has taken, when it opens', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    // 11:52 AM in Kansas City: the ingest publishes a blank file, and the map takes it.
    const blank = testClosings('2026-01-12T17:52:00Z', meta, []);
    await closingsReader(files).read({ fetch: () => Promise.resolve(jsonResponse(blank)) });
    // A minute later a parent opens the school. The panel's first read gets the 11:40 file,
    // the school closed: an edge behind, or the worker's copy when the network is slow.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(10);
    // One read of the closings file, beside the first read of the chances.
    expect(
      fetchImpl.mock.calls.filter(([url]) => urlOf(url).endsWith('live/closings.json')),
    ).toHaveLength(1);
    const shown = views.filter((view) => view !== null && !view.loading);
    expect(shown.length).toBeGreaterThan(0);
    expect(shown.every((view) => view?.status.length === 0)).toBe(true);
    stop();
  });

  it('opens with the file the map holds, and reads no more often than the map', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const closingsReads = (): number =>
      fetchImpl.mock.calls.filter(([url]) => urlOf(url).endsWith('live/closings.json')).length;
    const live = startLive({
      files,
      directory: () => Promise.resolve(null),
      onLight: () => undefined,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(closingsReads()).toBe(1);
    // The panel opens 20 seconds later: the map's file, at once, with no read of its own.
    await vi.advanceTimersByTimeAsync(20_000);
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(closingsReads()).toBe(1);
    expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
    // Ten minutes with the panel open: one read of the closings file a minute, not two.
    await vi.advanceTimersByTimeAsync(10 * LIVE_POLL_MS);
    expect(closingsReads()).toBe(11);
    stop();
    live.stop();
  });

  for (const back of [15, 60]) {
    it(`drops a closed status within one poll of a blank published after the clock went back ${String(back)} minutes`, async () => {
      vi.useFakeTimers();
      vi.setSystemTime(NOON);
      const files = withLiveRoot(
        createDataFiles(['schools/details/index.0123456789.json'], ROOT),
        LIVE,
      );
      // Taken at the device's own now, the school closed.
      const closed = testClosings('2026-01-12T18:00:00Z', meta, [testDay('2026-01-12', [[2, 0]])]);
      let current: unknown = closed;
      vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
        Promise.resolve(jsonResponse(current)),
      );
      const views: (SchoolView | null)[] = [];
      const stop = watchSchool({
        files,
        details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: closed.directory })) },
        id: PRIVATE.id,
        hint: null,
        onView: (view) => views.push(view),
        now: () => new Date(Date.now()),
        timeZone: () => 'America/Chicago',
      });
      await vi.advanceTimersByTimeAsync(10);
      expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
      // The device's clock goes back; the ingest publishes a blank, stamped past that clock.
      vi.setSystemTime(NOON.getTime() - back * 60_000);
      current = testClosings('2026-01-12T18:01:00Z', meta, []);
      await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
      expect(views.at(-1)?.status).toEqual([]);
      stop();
    });
  }

  it('shows at once a newer file the map took, before its own next read', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
    // The map's poll takes a blank the worker said is newer; no panel timer has fired.
    const blank = testClosings('2026-01-12T17:52:00Z', meta, []);
    await closingsReader(files).read({
      force: true,
      fetch: () => Promise.resolve(jsonResponse(blank)),
    });
    expect(views.at(-1)?.status).toEqual([]);
    expect(
      fetchImpl.mock.calls.filter(([url]) => urlOf(url).endsWith('closings.json')),
    ).toHaveLength(1);
    stop();
  });

  it('reads nothing while the page is hidden', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    const stop = watchSchool({
      files: createDataFiles(['live/closings.json', 'schools/details/index.0123456789.json'], ROOT),
      details: { get: vi.fn(() => Promise.resolve(PRIVATE)) },
      id: PRIVATE.id,
      hint: null,
      onView: () => undefined,
      pollMs: 1000,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(10);
    // The first read, as the panel opens.
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    // Seen, it reads each period; hidden again, it stops.
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    visibility.mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    stop();
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    visibility.mockRestore();
  });

  it('beside the map, reads within a poll of the read made when the page is shown again, and shows a blank within it', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    let current: unknown = newer;
    const reads: number[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      if (urlOf(url).endsWith('closings.json')) reads.push(performance.now());
      return Promise.resolve(jsonResponse(current));
    });
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const map = startLive({
      files,
      directory: () => Promise.resolve(null),
      onLight: () => undefined,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(10);
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(views.at(-1)?.status).toMatchObject([{ tone: 'closed' }]);
    // The phone is locked, and unlocked 66 s later: a read at once, for the map and the panel.
    visibility.mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(66_000);
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10);
    const shownRead = reads.at(-1) ?? 0;
    expect(performance.now() - shownRead).toBeLessThan(100);
    // A blank published just after it shows in the panel within a poll.
    current = testClosings('2026-01-12T17:52:00Z', meta, []);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(views.at(-1)?.status).toEqual([]);
    await vi.advanceTimersByTimeAsync(4 * LIVE_POLL_MS);
    const after = reads.filter((time) => time >= shownRead);
    const gaps = after.slice(1).map((time, i) => time - (after[i] ?? time));
    expect(Math.max(...gaps)).toBeLessThanOrEqual(LIVE_POLL_MS);
    // One read a poll for the two of them.
    expect(after.length).toBe(6);
    stop();
    map.stop();
    visibility.mockRestore();
  });

  for (const panelFirst of [false, true]) {
    const order = panelFirst ? 'opened before the map starts' : 'opened beside the map';
    it(`${order}, with the ingest stopped, drops yesterday's closing within a poll of the day turning and reads its side files every five minutes`, async () => {
      vi.useFakeTimers();
      // Monday evening in the US (03:30 UTC Tuesday). The last file, at 03:20, holds Monday's
      // closing; the ingest stops, so it is served all night.
      vi.setSystemTime(new Date('2026-01-13T03:30:00Z'));
      const monday = testClosings('2026-01-13T03:20:00Z', meta, [testDay('2026-01-12', [[2, 0]])]);
      const files = withLiveRoot(
        createDataFiles(
          ['schools/details/index.0123456789.json', 'live/covered.json', 'predictions/latest.json'],
          ROOT,
        ),
        LIVE,
      );
      const reads = { closings: 0, covered: 0, predictions: 0 };
      vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
        const href = urlOf(url);
        if (href.endsWith('closings.json')) reads.closings += 1;
        if (href.endsWith('covered.json')) reads.covered += 1;
        if (href.endsWith('latest.json')) reads.predictions += 1;
        return Promise.resolve(jsonResponse(monday));
      });
      const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
      const views: { at: number; view: SchoolView | null }[] = [];
      const panel = (): (() => void) =>
        watchSchool({
          files,
          details: {
            get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: monday.directory })),
          },
          id: PRIVATE.id,
          hint: null,
          onView: (view) => views.push({ at: Date.now(), view }),
          now: () => new Date(Date.now()),
          timeZone: () => 'America/Chicago',
        });
      let stop = panelFirst ? panel() : null;
      const map = startLive({
        files,
        directory: () => Promise.resolve(null),
        onLight: () => undefined,
        now: () => new Date(Date.now()),
      });
      await vi.advanceTimersByTimeAsync(10);
      stop ??= panel();
      await vi.advanceTimersByTimeAsync(1000);
      expect(views.at(-1)?.view?.status).toMatchObject([{ tone: 'closed' }]);
      const opened = { ...reads };
      // Seven hours on, the page seen all night: at 04:00 UTC Monday is no longer today
      // everywhere, and from 08:00 Tuesday is.
      await vi.advanceTimersByTimeAsync(7 * 60 * LIVE_POLL_MS);
      const turn = Date.parse('2026-01-13T04:00:00Z');
      const cleared = views.find(({ at, view }) => at >= turn && view?.status.length === 0);
      expect(cleared, 'the closing dropped after the day turned').toBeDefined();
      expect((cleared?.at ?? Infinity) - turn).toBeLessThanOrEqual(LIVE_POLL_MS);
      expect(
        views.filter(({ at }) => at >= turn).every(({ view }) => view?.status.length === 0),
      ).toBe(true);
      // One closings read a poll for the map and the panel; the side files every five minutes.
      expect(reads.closings - opened.closings).toBe(7 * 60);
      expect(reads.covered - opened.covered).toBe((7 * 60 * LIVE_POLL_MS) / LIVE_SIDE_POLL_MS);
      expect(reads.predictions - opened.predictions).toBe(
        (7 * 60 * LIVE_POLL_MS) / LIVE_SIDE_POLL_MS,
      );
      stop();
      map.stop();
      visibility.mockRestore();
    });
  }

  it('reads within a poll of a forced read the reader made between its own polls', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    let current: unknown = newer;
    const reads: number[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      if (urlOf(url).endsWith('closings.json')) reads.push(performance.now());
      return Promise.resolve(jsonResponse(current));
    });
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(40_000);
    // The worker said it holds a newer copy, 40 s into the panel's minute: a forced read.
    await closingsReader(files).read({ force: true });
    const forced = reads.at(-1) ?? 0;
    current = testClosings('2026-01-12T17:52:00Z', meta, []);
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(views.at(-1)?.status).toEqual([]);
    expect(reads.filter((time) => time > forced)).toHaveLength(1);
    expect((reads.at(-1) ?? 0) - forced).toBeLessThanOrEqual(LIVE_POLL_MS);
    stop();
  });

  it('reads nothing while hidden, whatever wakes the page: a gap in the clock, focus, pageshow or resume', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    const stop = watchSchool({
      files: withLiveRoot(createDataFiles(['schools/details/index.0123456789.json'], ROOT), LIVE),
      details: { get: vi.fn(() => Promise.resolve(PRIVATE)) },
      id: PRIVATE.id,
      hint: null,
      onView: () => undefined,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(2 * LIVE_POLL_MS);
    // The closings at the open and each minute, and the chances at the open (every five minutes).
    const seen = fetchImpl.mock.calls.length;
    expect(seen).toBe(4);
    // A poll is due as the page is hidden.
    vi.setSystemTime(Date.now() + 2 * LIVE_POLL_MS);
    visibility.mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    for (let i = 0; i < 30; i += 1) {
      // A hidden page's timers run at most once a minute: each wake check sees a minute's gap.
      vi.setSystemTime(Date.now() + LIVE_POLL_MS);
      await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
      window.dispatchEvent(new Event('focus'));
      window.dispatchEvent(new Event('pageshow'));
      document.dispatchEvent(new Event('resume'));
      document.dispatchEvent(new Event('visibilitychange'));
      await vi.advanceTimersByTimeAsync(0);
    }
    expect(fetchImpl.mock.calls.length - seen).toBe(0);
    // Seen again: it reads at once, the closings and (five minutes on) the chances.
    visibility.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchImpl.mock.calls.length - seen).toBe(2);
    stop();
  });

  it('stops hearing the page’s reader when it stops, so a later file reaches no closed panel', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const files = withLiveRoot(
      createDataFiles(['schools/details/index.0123456789.json'], ROOT),
      LIVE,
    );
    const reader = closingsReader(files);
    const stops: ReturnType<typeof vi.fn>[] = [];
    const subscribe = reader.subscribe.bind(reader);
    vi.spyOn(reader, 'subscribe').mockImplementation((listener) => {
      const stopIt = vi.fn(subscribe(listener));
      stops.push(stopIt);
      return stopIt;
    });
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(jsonResponse(older)));
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: vi.fn(() => Promise.resolve({ ...PRIVATE, directory: newer.directory })) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      timeZone: () => 'America/Chicago',
    });
    await vi.advanceTimersByTimeAsync(10);
    expect(stops).toHaveLength(1);
    stop();
    expect(stops[0]).toHaveBeenCalledTimes(1);
    const shown = views.length;
    await reader.read({ force: true, fetch: () => Promise.resolve(jsonResponse(newer)) });
    await vi.advanceTimersByTimeAsync(10);
    expect(reader.current?.generated_at).toBe(newer.generated_at);
    expect(views.length).toBe(shown);
  });

  it('reads the closings file each minute, and covered and predictions every five', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOON);
    const fetchImpl = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(() => Promise.resolve(jsonResponse(newer)));
    const stop = watchSchool({
      files: withLiveRoot(
        createDataFiles(
          ['live/covered.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
          ROOT,
        ),
        LIVE,
      ),
      details: { get: vi.fn(() => Promise.resolve(PRIVATE)) },
      id: PRIVATE.id,
      hint: null,
      onView: () => undefined,
      now: () => NOON,
    });
    await vi.advanceTimersByTimeAsync(10 * LIVE_POLL_MS + 10);
    const reads = (part: string): number =>
      fetchImpl.mock.calls.filter(([url]) => urlOf(url).includes(part)).length;
    expect(LIVE_SIDE_POLL_MS).toBe(5 * LIVE_POLL_MS);
    expect(reads('live/closings.json')).toBe(11);
    // At the open, and five and ten minutes on.
    expect(reads('live/covered.json')).toBe(3);
    expect(reads('predictions/latest.json')).toBe(3);
    // After a sleep, all of them at once.
    vi.setSystemTime(Date.now() + 60 * 60_000);
    await vi.advanceTimersByTimeAsync(WAKE_CHECK_MS);
    expect(reads('live/closings.json')).toBe(12);
    expect(reads('live/covered.json')).toBe(4);
    expect(reads('predictions/latest.json')).toBe(4);
    stop();
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
        time_zone: 'America/Chicago',
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
              base: { kind: 'similar_days', points: 30, borrowed: false, live: false },
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

  it('gives a public school its district’s chance, and a private school its own', () => {
    const outlook = {
      today: { state: 'no_threat' } as const,
      tomorrow: {
        state: 'forecast' as const,
        noSchool: 0.45,
        delay: 0.2,
        reasons: [0 as const],
        day: '2026-01-13',
      },
      timeZone: 'America/Chicago',
    };
    const view = schoolView(input({ id: record.id, record, outlook, now: evening }));
    expect(view?.chance).toMatchObject({
      number: '45',
      meaning: 'Chance of no school Tuesday',
      delay: '20% chance of a delayed start instead',
    });
    // A private school's own outlook (contract C3): its own chance, the same way.
    expect(schoolView(input({ outlook, now: evening }))?.chance).toMatchObject({
      number: '45',
      meaning: 'Chance of no school Tuesday',
    });
    // With no chance to give, the panel shows the status lines alone.
    expect(schoolView(input({ id: record.id, record, now: evening }))?.chance).toBeNull();
  });

  it('leaves a day’s chance out beside that day’s status: the fact beats the forecast', () => {
    const today: DayOutlook = {
      state: 'forecast',
      noSchool: 0.97,
      delay: 0.02,
      reasons: [0],
      day: '2026-01-12',
    };
    const tomorrow: DayOutlook = {
      state: 'forecast',
      noSchool: 0.4,
      delay: 0.2,
      reasons: [],
      day: '2026-01-13',
    };
    const outlook = { today, tomorrow, timeZone: 'America/Chicago' };
    const closed: StatusRow = {
      status: 0,
      reason: 0,
      announcedAt: null,
      shiftMinutes: null,
      clockMinute: null,
      manual: false,
    };
    /** 4 AM in Kansas City, before the day is under way at 5. */
    const morning = new Date('2026-01-12T10:00:00Z');
    const view = (status: SchoolStatus) =>
      schoolView(input({ id: record.id, record, status, outlook, now: morning }));
    // Closed today: tomorrow's chance.
    expect(view({ today: closed, tomorrow: null })?.chance?.day).toBe('2026-01-13');
    // "Open today" decides nothing: today's chance stays beside the open line.
    expect(view({ today: 'open', tomorrow: null })?.chance?.day).toBe('2026-01-12');
    // Both days decided: no chance to give.
    expect(view({ today: closed, tomorrow: closed })?.chance).toBeNull();
  });

  it('leaves a private school’s own chance out beside a status our team set for that day', () => {
    // A private school (no district) with its own outlook (contract C3), and a manual row from
    // the admin (the closings file's manual column) closing it today.
    const outlook = {
      today: {
        state: 'forecast' as const,
        noSchool: 0.42,
        delay: 0.05,
        reasons: [0 as const],
        day: '2026-01-12',
      },
      tomorrow: {
        state: 'forecast' as const,
        noSchool: 0.3,
        delay: 0.1,
        reasons: [0 as const],
        day: '2026-01-13',
      },
      timeZone: 'America/Chicago',
    };
    const manual: StatusRow = {
      status: 0,
      reason: 0,
      announcedAt: null,
      shiftMinutes: null,
      clockMinute: null,
      manual: true,
    };
    /** 4 AM in Kansas City, before the day is under way at 5. */
    const morning = new Date('2026-01-12T10:00:00Z');
    const view = (status: SchoolStatus) => schoolView(input({ status, outlook, now: morning }));
    // With no status: its own chance today.
    expect(view({ today: null, tomorrow: null })?.chance).toMatchObject({
      number: '42',
      day: '2026-01-12',
    });
    // Closed today by our team: today's chance is gone, tomorrow's stands.
    expect(view({ today: manual, tomorrow: null })?.chance).toMatchObject({
      number: '30',
      day: '2026-01-13',
    });
    // Both days set by our team: no chance to give.
    expect(view({ today: manual, tomorrow: manual })?.chance).toBeNull();
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
      'Maries County usually announces',
    ]);
    // The timeline names them, so the sum only names the reason.
    expect(named?.why?.lines.map((line) => `${line.points} ${line.text}`)).toEqual([
      '+15 Districts next door canceled.',
    ]);
    // Before the directory came, the same sum, by how many.
    const first = views.find((view) => (view?.chance ?? null) !== null)?.chance;
    expect(first?.moments.map((moment) => moment.mark)).toEqual(['announces']);
    expect(first?.why?.lines[0]?.text).toBe('2 districts next door canceled.');
    expect(directory).toHaveBeenCalledTimes(1);
    expect(directory).toHaveBeenCalledWith(stamp);
    stop();
    fetchImpl.mockRestore();
  });

  it('counts the schools the directory gives each district, so a status is the whole district’s', () => {
    const schools = [
      { id: '290000199999', name: 'BELLE ELEM.', lon: -94.6, lat: 39, district: 0 },
      { id: '290000299999', name: 'NEXT DOOR ELEM.', lon: -94.5, lat: 39, district: 1 },
      { id: '290000499999', name: 'NEXT DOOR HIGH', lon: -94.5, lat: 39, district: 1 },
      { id: 'A9999999', name: 'PRIVATE ACADEMY', lon: -94.5, lat: 39, district: -1, kind: 1 },
    ];
    const four = testMeta(schools, ['2999999', '2900002', '2900003']);
    const points = parsePoints(testPoints(schools, 3), four);
    if (points === null) throw new Error('no points');
    const names = namesOf(createDirectory(four, points));
    expect([0, 1, 2, 3, -1].map((district) => names.schools(district))).toEqual([1, 2, 0, 0, 0]);
  });

  it('gives no chance from a predictions file the passes stopped writing', async () => {
    const files = createDataFiles(
      ['live/closings.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    const fetchImpl = vi.spyOn(globalThis, 'fetch').mockImplementation((request) => {
      const url = request instanceof Request ? request.url : request.toString();
      return Promise.resolve(jsonResponse(url.includes('predictions') ? predictions : closings));
    });
    const watch = async (now: Date): Promise<SchoolView | null> => {
      const views: (SchoolView | null)[] = [];
      const stop = watchSchool({
        files,
        details: { get: vi.fn(() => Promise.resolve(record)) },
        id: record.id,
        hint: null,
        onView: (view) => views.push(view),
        now: () => now,
        timeZone: () => 'America/Chicago',
      });
      await vi.waitFor(() => {
        expect(views.at(-1)?.loading).toBe(false);
        expect(fetchImpl).toHaveBeenCalled();
      }, WAIT);
      await new Promise((resolve) => setTimeout(resolve, 0));
      stop();
      return views.at(-1) ?? null;
    };
    // Made at 9 PM: read at 10:30 PM, its chance; at 10:31 PM, none, never the old one.
    expect((await watch(new Date('2026-01-13T04:30:00Z')))?.chance?.number).toBe('45');
    fetchImpl.mockClear();
    expect((await watch(new Date('2026-01-13T04:31:00Z')))?.chance).toBeNull();
    fetchImpl.mockRestore();
  });
});

describe('a school on a past day', () => {
  /** SYNTHETIC: the replay day had the school closed for a winter storm, and one neighbor remote. */
  const REPLAY = {
    day: '2026-01-05',
    lookup: (id: string) =>
      id === PRIVATE.id
        ? { status: 0 as const, reason: 0 }
        : id === 'ZZ000004'
          ? { status: 2 as const, reason: null }
          : null,
  };

  it('gives the day’s status dated with its year and its reason, and no chance', () => {
    const view = schoolView(input({ record: PUBLIC, id: PUBLIC.id, replay: REPLAY }));
    expect(view?.status).toEqual([]);
    expect(view?.chance).toBeNull();
    const lit = schoolView(input({ replay: REPLAY }));
    expect(lit?.status).toEqual([
      {
        tone: 'closed',
        headline: 'Closed Mon, Jan 5, 2026',
        detail: null,
        note: copy.reason.winterStorm,
      },
    ]);
    expect(lit?.chance).toBeNull();
    // The nearby schools' marks are that day's too.
    expect(lit?.nearby.map(({ tone }) => tone)).toEqual([null, 'remote']);
  });

  it('never says Open, today, tomorrow or Posted, whatever the live files hold', () => {
    const status: SchoolStatus = {
      today: 'open',
      tomorrow: { status: 0, reason: 0, announcedAt: NOON, shiftMinutes: null, clockMinute: null },
    } as unknown as SchoolStatus;
    const view = schoolView(input({ record: PUBLIC, id: PUBLIC.id, status, replay: REPLAY }));
    const lit = schoolView(input({ status, replay: REPLAY }));
    const text = JSON.stringify([view?.status, lit?.status]);
    expect(text).not.toMatch(/Open|today|tomorrow|Posted/u);
  });

  it('reads no live file and polls nothing', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    const fetchImpl = vi.spyOn(globalThis, 'fetch');
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files: createDataFiles(
        ['live/closings.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
        ROOT,
      ),
      details: { get: vi.fn(() => Promise.resolve(PRIVATE)) },
      id: PRIVATE.id,
      hint: null,
      onView: (view) => views.push(view),
      now: () => NOON,
      replay: REPLAY,
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
    }, WAIT);
    expect(views.at(-1)?.status[0]?.headline).toBe('Closed Mon, Jan 5, 2026');
    vi.advanceTimersByTime(60 * 60_000);
    expect(fetchImpl).not.toHaveBeenCalled();
    stop();
    fetchImpl.mockRestore();
    vi.useRealTimers();
  });
});

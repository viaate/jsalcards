/**
 * Every list, heading and panel beside the map tells a school's day as the map
 * lights it (data/map-day.ts): the area panel's list and the school panel's
 * nearby list draw each school's glyph from its own light, the area's counts
 * are headed by the day they are for, and a school's panel names the row its
 * light shows, whether its own read of the predictions file comes or not.
 * Every file here is SYNTHETIC, made up for these tests.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { STATUS_KEYS, copy } from '../../copy';
import type { StatusKey } from '../../copy';
import type { AreaRecord } from '../../data/areas';
import { lightSchools } from '../../data/closings';
import type { DetailsSource, SchoolRecord } from '../../data/details';
import { createDirectory, parsePoints } from '../../data/directory';
import { createDataFiles } from '../../data/files';
import { predictionsReader } from '../../data/live';
import { zonesOf } from '../../data/map-day';
import type { ToldZones } from '../../data/map-day';
import { NO_STATUS, parsePredictions } from '../../data/school-day';
import {
  jsonResponse,
  testClosings,
  testDay,
  testMeta,
  testPoints,
} from '../../data/tests/builders';
import type { TestSchool } from '../../data/tests/builders';
import { areaView, watchArea } from '../area';
import { schoolView, watchSchool } from '../school';
import type { SchoolView } from '../school';
import type { AreaView } from '../area';

const ROOT = 'https://snow.test/data/';
/** New York, Los Angeles, a private school on Chicago's clock, Anchorage and Honolulu. */
const SCHOOLS: TestSchool[] = [
  { id: '360000100001', name: 'EAST EL', lon: -73.9, lat: 40.7, district: 0 },
  { id: '060000100001', name: 'WEST EL', lon: -118.2, lat: 34.0, district: 1 },
  { id: 'A0000001', name: 'MIDDLE ACADEMY', lon: -94.6, lat: 39.0, district: -1, kind: 1 },
  { id: '020000100001', name: 'NORTH EL', lon: -149.9, lat: 61.2, district: 2 },
  { id: '150000100001', name: 'ISLAND EL', lon: -157.86, lat: 21.31, district: 3 },
];
const STATES = ['NY', 'CA', 'IL', 'AK', 'HI'];
const DISTRICT_IDS = ['3600001', '0600001', '0200001', '1500001'];
const META = testMeta(SCHOOLS, DISTRICT_IDS);
const POINTS = parsePoints(testPoints(SCHOOLS, DISTRICT_IDS.length), META);
if (POINTS === null) throw new Error('points did not parse');
const DIRECTORY = createDirectory(META, POINTS);
const STAMP = { generated_on: META.generated_on, schools: SCHOOLS.length, districts: 4 };

const PREDICTIONS_JSON = {
  schema_version: 1,
  generated_at: '2026-11-09T12:00:00Z',
  directory: STAMP,
  days: ['2026-11-09', '2026-11-10'],
  districts: [
    'America/New_York',
    'America/Los_Angeles',
    'America/Anchorage',
    'Pacific/Honolulu',
  ].map((zone, district) => ({
    district,
    time_zone: zone,
    days: [{ state: 'no_threat' }, { state: 'no_threat' }],
  })),
  outlooks: [{ state: 'no_threat' }],
  zones: ['America/Chicago'],
  schools: [{ school: 2, zone: 0, days: [0, 0] }],
};
const PREDICTIONS = parsePredictions(PREDICTIONS_JSON);
if (PREDICTIONS === null) throw new Error('the made-up predictions file did not parse');
const ZONES = zonesOf(PREDICTIONS);

/** Monday: every school has a row; Tuesday: each a different one. */
const FILE = testClosings('2026-11-09T12:00:00Z', META, [
  testDay('2026-11-09', [
    [0, 0],
    [1, 1],
    [2, 0],
    [3, 0],
    [4, 0],
  ]),
  testDay('2026-11-10', [
    [0, 2],
    [1, 3],
    [2, 1],
    [3, 2],
    [4, 1],
  ]),
]);

function record(index: number): SchoolRecord {
  const school = SCHOOLS[index];
  if (school === undefined) throw new Error('no such school');
  const district = school.district;
  return {
    id: school.id,
    index,
    name: school.name,
    private: district < 0,
    charter: false,
    virtual: false,
    district:
      district < 0
        ? null
        : { index: district, id: DISTRICT_IDS[district] ?? '', name: 'A DISTRICT' },
    street: null,
    city: null,
    state: STATES[index] ?? 'NY',
    zip: null,
    county: null,
    grades: null,
    enrollment: 100,
    phone: null,
    nearby: SCHOOLS.flatMap((near, at) =>
      at === index
        ? []
        : [{ index: at, id: near.id, name: near.name, metres: 1000, lon: near.lon, lat: near.lat }],
    ),
    directory: STAMP,
  };
}

const AREA: AreaRecord = {
  zip: '10001',
  lon: -73.9,
  lat: 40.7,
  states: ['NY'],
  own: SCHOOLS.map((school, index) => ({
    index,
    id: school.id,
    metres: 100 * (index + 1),
    lon: school.lon,
    lat: school.lat,
  })),
  near: [],
  directory: STAMP,
};
const RECORDS = new Map(SCHOOLS.map((school, index) => [school.id, record(index)]));

/** Each lit school's status key, as the map lights it, by school id. */
function lights(now: Date, told: ToldZones): Map<string, StatusKey> {
  const shown = lightSchools(FILE, DIRECTORY, {
    now,
    previous: null,
    bornMs: 0,
    zones: told ?? null,
    unread: told === undefined,
  });
  return new Map(
    [...shown.schools].map((school, row) => [
      SCHOOLS[school]?.id ?? '',
      STATUS_KEYS[shown.status[row] ?? 0] ?? 'closed',
    ]),
  );
}

/** Every quarter hour of a day and a night, Monday noon UTC to Tuesday noon UTC. */
const INSTANTS = Array.from(
  { length: 97 },
  (_, i) => new Date(Date.parse('2026-11-09T12:00:00Z') + i * 15 * 60_000),
);
const TOLD: readonly [string, ToldZones][] = [
  ['zones read', ZONES],
  ['zones unread', undefined],
  ['no predictions shipped', null],
];

describe('the lists beside the map draw each glyph from the school’s light', () => {
  it('the area panel’s list: a glyph for every lit school, its light’s, and none for a dark one', () => {
    for (const [name, told] of TOLD) {
      for (const now of INSTANTS) {
        const view = areaView({
          zip: AREA.zip,
          hint: null,
          area: AREA,
          records: RECORDS,
          settled: true,
          live: { closings: FILE, covered: null, predictions: null },
          shipped: false,
          now,
          timeZone: 'America/New_York',
          told,
        });
        const tones = new Map((view?.own ?? []).map((row) => [row.id, row.tone]));
        const lit = lights(now, told);
        for (const school of SCHOOLS) {
          expect(tones.get(school.id) ?? null, `${name} ${now.toISOString()} ${school.name}`).toBe(
            lit.get(school.id) ?? null,
          );
        }
      }
    }
  });

  it('the school panel’s nearby list, by each nearby school’s own zone', () => {
    for (const [name, told] of TOLD) {
      for (const now of INSTANTS) {
        const view = schoolView({
          id: SCHOOLS[0]?.id ?? '',
          hint: null,
          record: record(0),
          settled: true,
          status: NO_STATUS,
          outlook: null,
          closings: FILE,
          nearbyZones: { told, districtOf: (school) => DIRECTORY.district[school] ?? -1 },
          now,
          timeZone: 'America/New_York',
        });
        const lit = lights(now, told);
        for (const near of view?.nearby ?? []) {
          expect(near.tone, `${name} ${now.toISOString()} ${near.name}`).toBe(
            lit.get(near.id) ?? null,
          );
        }
      }
    }
  });

  it('at 9 PM in New York, the light’s Tuesday glyph, never Monday’s finished closing', () => {
    // The critic's probe: a school closed Monday only, and one remote Tuesday only.
    const file = testClosings('2026-11-09T21:00:00Z', META, [
      testDay('2026-11-09', [[0, 0]]),
      testDay('2026-11-10', [[2, 2]]),
    ]);
    const near = (at: string): (StatusKey | null)[] =>
      schoolView({
        id: SCHOOLS[1]?.id ?? '',
        hint: null,
        record: record(1),
        settled: true,
        status: NO_STATUS,
        outlook: null,
        closings: file,
        nearbyZones: { told: ZONES, districtOf: (school) => DIRECTORY.district[school] ?? -1 },
        now: new Date(at),
        timeZone: 'America/New_York',
      })?.nearby.map((row) => row.tone) ?? [];
    // 4 PM in New York (East on Tuesday, no row), 3 PM in Chicago (Middle on Monday, no row).
    expect(near('2026-11-09T21:00:00Z')).toEqual([null, null, null, null]);
    // 8 PM in Chicago: Middle on Tuesday, remote.
    expect(near('2026-11-10T02:00:00Z')).toEqual([null, 'remote', null, null]);
    // 05:30 UTC, past midnight in the East: still Tuesday, still lit.
    expect(near('2026-11-10T05:30:00Z')).toEqual([null, 'remote', null, null]);
  });

  it('heads the area’s counts with the day they are for, both while the area shows two', () => {
    const label = (at: string, told: ToldZones = ZONES): string | undefined =>
      areaView({
        zip: AREA.zip,
        hint: null,
        area: AREA,
        records: RECORDS,
        settled: true,
        live: { closings: FILE, covered: null, predictions: null },
        shipped: false,
        now: new Date(at),
        timeZone: 'America/New_York',
        told,
      })?.tallyLabel;
    // Morning everywhere: today, on every clock and the visitor's.
    expect(label('2026-11-10T15:00:00Z')).toBe(copy.days.today);
    // 4 PM in New York, noon in Honolulu: the East on Tuesday, the rest on Monday.
    expect(label('2026-11-09T21:00:00Z')).toBe('Monday and Tuesday');
    // Past 3:30 PM in Honolulu: Tuesday everywhere, never Today.
    expect(label('2026-11-10T02:00:00Z')).toBe('Tuesday');
    // A visitor already past midnight in New York, every school still on its evening: Tuesday.
    expect(label('2026-11-10T05:30:00Z')).toBe('Tuesday');
  });
});

describe('a school’s panel names the row its light shows', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** Opens West's (or `index`'s) panel at `at`, with the predictions file `served` or failing. */
  async function panel(
    at: string,
    options: { index?: number; held: boolean; served: boolean },
  ): Promise<SchoolView | null> {
    const files = createDataFiles(
      ['live/closings.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    if (options.held) {
      // The page's reader already holds the file the map reads its zones from.
      await predictionsReader(files).read({
        fetch: () => Promise.resolve(jsonResponse(PREDICTIONS_JSON)),
      });
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      const asked = url instanceof Request ? url.url : url.toString();
      if (asked.includes('predictions/latest.json')) {
        return options.served
          ? Promise.resolve(jsonResponse(PREDICTIONS_JSON))
          : Promise.reject(new TypeError('offline'));
      }
      return Promise.resolve(jsonResponse(FILE));
    });
    const index = options.index ?? 1;
    const details: DetailsSource = { get: () => Promise.resolve(record(index)) };
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details,
      id: SCHOOLS[index]?.id ?? '',
      hint: null,
      onView: (view) => views.push(view),
      now: () => new Date(at),
      timeZone: () => 'America/New_York',
      directory: () => Promise.resolve(DIRECTORY),
    });
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
    });
    stop();
    return views.at(-1) ?? null;
  }

  it('its own read failed, the page’s zones held: at 05:30 UTC the row the map lights', async () => {
    // 9:30 PM in Los Angeles: West is lit with Tuesday's early dismissal.
    expect(lights(new Date('2026-11-10T05:30:00Z'), ZONES).get(SCHOOLS[1]?.id ?? '')).toBe(
      'earlyDismissal',
    );
    const view = await panel('2026-11-10T05:30:00Z', { held: true, served: false });
    expect(view?.status.map((line) => [line.tone, line.headline])).toEqual([
      ['delayed', copy.statusLine.delayed.today],
      ['earlyDismissal', copy.statusLine.earlyDismissal.tomorrow],
    ]);
  });

  it('no zones to be had at all: the panel names a day only where the map lights one', async () => {
    // 05:30 UTC: no day every contiguous clock calls today. The map lights nothing; the panel
    // names nothing.
    expect(lights(new Date('2026-11-10T05:30:00Z'), undefined).size).toBe(0);
    const late = await panel('2026-11-10T05:30:00Z', { held: false, served: false });
    expect(late?.status).toEqual([]);
    // 02:00 UTC: Monday on every clock, past 3:30 PM on each, but Monday still the day of a
    // school with no zone: none lit. The panel's today and tomorrow are Monday and Tuesday on
    // every contiguous clock, and say so.
    expect(lights(new Date('2026-11-10T02:00:00Z'), undefined).size).toBe(0);
    const evening = await panel('2026-11-10T02:00:00Z', { held: false, served: false });
    expect(evening?.status.map((line) => line.headline)).toEqual([
      copy.statusLine.delayed.today,
      copy.statusLine.earlyDismissal.tomorrow,
    ]);
    // 18:00 UTC Tuesday: Tuesday everywhere and before 3:30 PM on every clock: Tuesday's row lit,
    // and the panel says it is today's.
    expect(lights(new Date('2026-11-10T18:00:00Z'), undefined).get(SCHOOLS[1]?.id ?? '')).toBe(
      'earlyDismissal',
    );
    const morning = await panel('2026-11-10T18:00:00Z', { held: false, served: false });
    expect(morning?.status.map((line) => line.headline)).toEqual([
      copy.statusLine.earlyDismissal.today,
    ]);
    // Honolulu, with no zone to be had: no light at any hour, and no day named in its panel.
    for (const at of INSTANTS) {
      expect(lights(at, undefined).has(SCHOOLS[4]?.id ?? '')).toBe(false);
    }
    const island = await panel('2026-11-10T02:00:00Z', { index: 4, held: false, served: false });
    expect(island?.status).toEqual([]);
  });

  it('its own read comes: the panel and the light by the same zone', async () => {
    const view = await panel('2026-11-10T05:30:00Z', { index: 4, held: false, served: true });
    // 7:30 PM in Honolulu: Tuesday's delay lit, tomorrow in its panel.
    expect(lights(new Date('2026-11-10T05:30:00Z'), ZONES).get(SCHOOLS[4]?.id ?? '')).toBe(
      'delayed',
    );
    expect(view?.status.map((line) => line.headline)).toEqual([
      copy.statusLine.closed.today,
      copy.statusLine.delayed.tomorrow,
    ]);
  });
});

describe('an open panel turns with the map’s lights at 3:30 PM, with no read', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  /** The live files served, the predictions file among them, counting each read. */
  function serve(): { files: ReturnType<typeof createDataFiles>; reads: () => number } {
    let reads = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      reads += 1;
      const asked = url instanceof Request ? url.url : url.toString();
      return Promise.resolve(
        jsonResponse(asked.includes('predictions/latest.json') ? PREDICTIONS_JSON : FILE),
      );
    });
    const files = createDataFiles(
      ['live/closings.json', 'predictions/latest.json', 'schools/details/index.0123456789.json'],
      ROOT,
    );
    return { files, reads: () => reads };
  }

  it('the school panel’s nearby glyph turns at the East’s 3:30 PM, the minute its light does', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    // West's panel open at 3:29:40 PM in New York.
    vi.setSystemTime(new Date('2026-11-09T20:29:40Z'));
    const { files, reads } = serve();
    const views: (SchoolView | null)[] = [];
    const stop = watchSchool({
      files,
      details: { get: () => Promise.resolve(record(1)) },
      id: SCHOOLS[1]?.id ?? '',
      hint: null,
      onView: (view) => views.push(view),
      timeZone: () => 'America/New_York',
      directory: () => Promise.resolve(DIRECTORY),
      // No read again for an hour: the turn alone shows it.
      pollMs: 3_600_000,
    });
    const east = (): StatusKey | null | undefined =>
      views.at(-1)?.nearby.find((near) => near.id === SCHOOLS[0]?.id)?.tone;
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
      expect(east()).toBe('closed');
    });
    expect(lights(new Date(), ZONES).get(SCHOOLS[0]?.id ?? '')).toBe('closed');
    const before = reads();
    // 3:30:00 PM and a moment: the East's light on Tuesday's remote day, and its glyph with it.
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:30:00Z') - Date.now() + 300);
    expect(lights(new Date(), ZONES).get(SCHOOLS[0]?.id ?? '')).toBe('remote');
    expect(east()).toBe('remote');
    expect(reads()).toBe(before);
    stop();
  });

  it('the area panel’s glyphs, counts and heading turn at the East’s 3:30 PM, the minute its lights do', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'],
    });
    vi.setSystemTime(new Date('2026-11-09T20:29:40Z'));
    const { files, reads } = serve();
    const views: (AreaView | null)[] = [];
    const stop = watchArea({
      files,
      areas: { shipped: true, get: () => Promise.resolve(AREA) },
      details: { get: (id: string) => Promise.resolve(RECORDS.get(id) ?? null) },
      zip: AREA.zip,
      hint: null,
      onView: (view) => views.push(view),
      timeZone: () => 'America/New_York',
      pollMs: 3_600_000,
    });
    const east = (): StatusKey | null | undefined =>
      views.at(-1)?.own.find((row) => row.id === SCHOOLS[0]?.id)?.tone;
    await vi.waitFor(() => {
      expect(views.at(-1)?.loading).toBe(false);
      expect(east()).toBe('closed');
    });
    expect(views.at(-1)?.tallyLabel).toBe(copy.days.today);
    const before = reads();
    await vi.advanceTimersByTimeAsync(Date.parse('2026-11-09T20:30:00Z') - Date.now() + 300);
    expect(east()).toBe('remote');
    // The counts are the lights': the East's remote day among them, and the heading names both.
    const lit = lights(new Date(), ZONES);
    const remote = [...lit.values()].filter((tone) => tone === 'remote').length;
    expect(remote).toBeGreaterThan(0);
    expect(views.at(-1)?.counts.find((count) => count.status === 'remote')).toBeDefined();
    expect(views.at(-1)?.tallyLabel).toBe('Monday and Tuesday');
    expect(reads()).toBe(before);
    stop();
  });
});

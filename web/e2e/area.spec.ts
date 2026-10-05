/**
 * The schools around a ZIP code: the area panel a ZIP code opens, picked in
 * search, typed and entered, or linked.
 *
 * Two builds with data staged in temporary folders, as app.spec.ts makes its
 * own. Both hold twelve schools as the pipeline's directory has them (their
 * ids, names, places, districts and students), the schools around 64130 and
 * 64112 as scripts/stage-data.mjs stages them (src/data/areas-format.ts), and
 * those two ZIP codes copied from the places build's records for search. Their
 * closings file is SYNTHETIC, and so is the predictions file the first build
 * ships: no real closings or forecasts exist in September, so the statuses and
 * chances are made up for this test and live only in the temporary folders
 * while it runs. The second build ships no predictions, as the site does today.
 *
 * Runs once, under the desktop project; tests set their own viewports. The
 * calendar is fixed alone (as app.spec.ts fixDate does): a faked clock would
 * stretch the map's flights by the frames it draws.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { devices, expect, test } from '@playwright/test';
import type { Browser, BrowserContextOptions, Page } from '@playwright/test';
import { build, preview } from 'vite';
import type { PreviewServer } from 'vite';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;
const BLOCKED_WORKER = 'Service Worker registration blocked by Playwright';
/** How long the map's first flight into streets may take under software WebGL (app.spec.ts). */
const FIRST_FLIGHT_MS = 90_000;

test.beforeEach(() => {
  test.skip(test.info().project.name !== 'desktop', 'Sets its own viewports; runs once.');
});

test.describe.configure({ timeout: 180_000, mode: 'default' });

const DESKTOP: BrowserContextOptions = { viewport: { width: 1440, height: 900 } };
const PHONE: BrowserContextOptions = devices['Pixel 7'];

/** SYNTHETIC: Monday Jan 12, 2026, 6:45 AM in Kansas City, the morning of a made-up storm. */
const NOW = new Date('2026-01-12T12:45:00Z');
const TODAY = '2026-01-12';

/** The directory's districts, in its order (by id). */
const DISTRICTS = [
  ['2011640', 'Shawnee Mission Pub Sch'],
  ['2900014', 'HOGAN PREPARATORY ACADEMY'],
  ['2900016', 'GENESIS SCHOOL INC.'],
  ['2900024', 'BROOKSIDE CHARTER SCH.'],
  ['2900025', 'ALLEN VILLAGE'],
  ['2916400', 'KANSAS CITY 33'],
] as const;

interface School {
  readonly id: string;
  readonly name: string;
  /** Kind flags: 0x01 private, 0x02 charter. */
  readonly kind: number;
  readonly district: number | null;
  readonly street: string;
  readonly city: string;
  readonly state: string;
  readonly zip: string;
  readonly county: string;
  readonly grades: readonly [string, string];
  readonly students: number;
  readonly phone: string;
  readonly lon: number;
  readonly lat: number;
}

/** Twelve schools as the pipeline's directory has them, in its order: public by id, then private. */
const SCHOOLS: readonly School[] = [
  {
    id: '201164001563',
    name: 'Westwood View Elem',
    kind: 0,
    district: 0,
    street: '4935 Belinder Ave',
    city: 'Westwood',
    state: 'KS',
    zip: '66205',
    county: 'Johnson County',
    grades: ['PK', '06'],
    students: 321,
    phone: '9139935800',
    lon: -94.615622,
    lat: 39.038229,
  },
  {
    id: '290001403222',
    name: 'HOGAN PREPARATORY ACADEMY ELEM',
    kind: 2,
    district: 1,
    street: '2803 E 51ST ST',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['PK', '06'],
    students: 391,
    phone: '8164445010',
    lon: -94.552097,
    lat: 39.033134,
  },
  {
    id: '290001602746',
    name: 'GENESIS SCHOOL INC.',
    kind: 2,
    district: 2,
    street: '3800 E 44TH ST',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['PK', '08'],
    students: 180,
    phone: '8169210775',
    lon: -94.539573,
    lat: 39.046492,
  },
  {
    id: '290002402838',
    name: 'BROOKSIDE CHARTER ELEMENTARY',
    kind: 2,
    district: 3,
    street: '1815 EAST 63RD STREET',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['PK', '05'],
    students: 575,
    phone: '8165312192',
    lon: -94.563663,
    lat: 39.012349,
  },
  {
    id: '290002403184',
    name: 'BROOKSIDE CHARTER MIDDLE SCHL',
    kind: 2,
    district: 3,
    street: '1815 EAST 63RD STREET',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['06', '08'],
    students: 225,
    phone: '8165312192',
    lon: -94.563663,
    lat: 39.012349,
  },
  {
    id: '290002502748',
    name: 'ALLEN VILLAGE ELEMENTARY ACADE',
    kind: 2,
    district: 4,
    street: '706 W 42ND ST',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64111',
    county: 'Jackson County',
    grades: ['03', '05'],
    students: 87,
    phone: '8169310177',
    lon: -94.594845,
    lat: 39.052917,
  },
  {
    id: '290002503233',
    name: 'ALLEN VILLAGE HIGH SCHOOL',
    kind: 2,
    district: 4,
    street: '706 WEST 42ND STREET',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64111',
    county: 'Jackson County',
    grades: ['09', '12'],
    students: 130,
    phone: '8169310177',
    lon: -94.592616,
    lat: 39.051364,
  },
  {
    id: '291640000818',
    name: 'CARVER DUAL LANGUAGE SCHOOL',
    kind: 0,
    district: 5,
    street: '4600 ELMWOOD AVE',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['PK', '06'],
    students: 468,
    phone: '8164184925',
    lon: -94.532128,
    lat: 39.042024,
  },
  {
    id: '291640000826',
    name: 'GEORGE MELCHER ELEMENTARY',
    kind: 0,
    district: 5,
    street: '3958 CHELSEA',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64130',
    county: 'Jackson County',
    grades: ['PK', '06'],
    students: 341,
    phone: '8164186735',
    lon: -94.52821,
    lat: 39.053673,
  },
  {
    id: '00753531',
    name: "ST TERESA'S ACADEMY",
    kind: 1,
    district: null,
    street: '5600 MAIN ST',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64113',
    county: 'Jackson County',
    grades: ['09', '12'],
    students: 570,
    phone: '8165010011',
    lon: -94.588971,
    lat: 39.02586,
  },
  {
    id: '00753542',
    name: 'VISITATION CATHOLIC SCHOOL',
    kind: 1,
    district: null,
    street: '5134 BALTIMORE AVE',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64112',
    county: 'Jackson County',
    grades: ['KG', '08'],
    students: 447,
    phone: '8165316200',
    lon: -94.588871,
    lat: 39.03368,
  },
  {
    id: 'A1902690',
    name: 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
    kind: 1,
    district: null,
    street: '400 W 51ST ST',
    city: 'KANSAS CITY',
    state: 'MO',
    zip: '64112',
    county: 'Jackson County',
    grades: ['PK', '12'],
    students: 1174,
    phone: '8169361230',
    lon: -94.593001,
    lat: 39.03606,
  },
];
const at = (id: string): number => SCHOOLS.findIndex((school) => school.id === id);

/** The two ZIP codes as the places build writes them (pipeline/out/site-data/search/zips.jsonl). */
const ZIP_RECORDS = [
  '{"districts":[{"leaid":"2916400","name":"Kansas City 33 School District","share":1.0}],"lat":39.036004,"lon":-94.59525,"states":["MO"],"zcta":"64112"}',
  '{"districts":[{"leaid":"2916400","name":"Kansas City 33 School District","share":1.0}],"lat":39.034782,"lon":-94.542049,"states":["MO"],"zcta":"64130"}',
];

/** Each ZIP code's own schools and the others taken in, nearest first, metres as staged. */
const AREAS = {
  '64112': {
    lon: -94.59525,
    lat: 39.036004,
    own: [
      ['A1902690', 194],
      ['00753542', 609],
    ],
    near: [
      ['00753531', 1252],
      ['290002503233', 1723],
      ['201164001563', 1777],
      ['290002502748', 1881],
    ],
  },
  '64130': {
    lon: -94.542049,
    lat: 39.034782,
    own: [
      ['290001403222', 887],
      ['291640000818', 1176],
      ['290001602746', 1320],
      ['291640000826', 2417],
      ['290002402838', 3116],
      ['290002403184', 3116],
    ],
    near: [],
  },
} as const;

const STAMP = { generated_on: '2026-09-25', schools: SCHOOLS.length, districts: DISTRICTS.length };

/** SYNTHETIC: today's statuses. Kansas City 33's two schools and Pembroke Hill closed, Westwood View remote. */
const POSTED: readonly (readonly [id: string, status: number])[] = [
  ['201164001563', 2],
  ['291640000818', 0],
  ['291640000826', 0],
  ['A1902690', 0],
];

/** SYNTHETIC: each district's chance of no school today; Genesis has no threat. */
const CHANCES: Readonly<Record<string, number | null>> = {
  '2011640': 0.35,
  '2900014': 0.55,
  '2900016': null,
  '2900024': 0.4,
  '2900025': 0.7,
  '2916400': 0.64,
};

function meta(): string {
  return JSON.stringify({
    schema_version: 1,
    generated_on: STAMP.generated_on,
    count: SCHOOLS.length,
    ids: SCHOOLS.map((school) => school.id),
    names: SCHOOLS.map((school) => school.name),
    districts: { ids: DISTRICTS.map(([id]) => id), names: DISTRICTS.map(([, name]) => name) },
    school_years: { public: '2024-2025', private: '2023-2024' },
  });
}

function points(): Buffer {
  const bytes = Buffer.alloc(16 + 13 * SCHOOLS.length);
  bytes.write('SLPT', 0, 'latin1');
  bytes.writeUInt16LE(1, 4);
  bytes.writeUInt16LE(13, 6);
  bytes.writeUInt32LE(SCHOOLS.length, 8);
  bytes.writeUInt32LE(DISTRICTS.length, 12);
  SCHOOLS.forEach((school, i) => {
    const offset = 16 + 13 * i;
    bytes.writeInt32LE(Math.round(school.lon * 1e6), offset);
    bytes.writeInt32LE(Math.round(school.lat * 1e6), offset + 4);
    bytes.writeUInt32LE(school.district ?? 0xffffffff, offset + 8);
    bytes.writeUInt8(school.kind, offset + 12);
  });
  return bytes;
}

/** The detail files (src/data/details-format.ts): one shard and its index. */
function details(): { index: string; shard: string } {
  const rows = SCHOOLS.map((school) => {
    const district = school.district === null ? null : DISTRICTS[school.district];
    return [
      school.id,
      school.name,
      school.kind,
      school.district,
      district?.[0] ?? null,
      district?.[1] ?? null,
      school.street,
      school.city,
      school.state,
      school.zip,
      school.county,
      school.grades[0],
      school.grades[1],
      school.students,
      school.phone,
      [],
    ];
  });
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_ids: [SCHOOLS[0]?.id],
      files: ['0.json'],
    }),
    shard: JSON.stringify({ schema_version: 1, directory: STAMP, first: 0, rows }),
  };
}

/** The area files (src/data/areas-format.ts): one shard and its index. */
function areas(): { index: string; shard: string } {
  const entry = ([id, metres]: readonly [string, number]): unknown[] => {
    const school = SCHOOLS[at(id)];
    return [at(id), id, metres, school?.lon, school?.lat];
  };
  const rows = Object.entries(AREAS).map(([zip, area]) => [
    zip,
    area.lon,
    area.lat,
    ['MO'],
    area.own.map(entry),
    area.near.map(entry),
  ]);
  return {
    index: JSON.stringify({
      schema_version: 1,
      directory: STAMP,
      shards: 1,
      first_zips: ['64112'],
      files: ['0.json'],
    }),
    shard: JSON.stringify({ schema_version: 1, directory: STAMP, first: '64112', areas: rows }),
  };
}

/** SYNTHETIC: the live file at 6:30 AM. */
function closings(): string {
  const posted = [...POSTED].sort((a, b) => at(a[0]) - at(b[0]));
  let before = -1;
  const gaps = posted.map(([id]) => {
    const gap = at(id) - before - 1;
    before = at(id);
    return gap;
  });
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:30:00Z',
    directory: STAMP,
    days: [
      {
        day: TODAY,
        gaps,
        statuses: posted.map(([, status]) => status),
        announced: posted.map((_, i) => 60 - i * 5),
        reasons: posted.map(() => 0),
        shifts: [],
        clocks: [],
      },
    ],
  });
}

/** SYNTHETIC: the chances made at 6:30 AM, in the shape the prediction engine is to write. */
function predictions(): string {
  const forecast = (chance: number): unknown => ({
    state: 'forecast',
    p_no_school: chance,
    p_delay: 0.1,
    reasons: [0],
    previous: null,
    announces_at: '2026-01-12T11:30:00Z',
    buses_at: '2026-01-12T13:00:00Z',
    hours: {
      kind: 'snow_total',
      start: '2026-01-12T01:00:00Z',
      values: [0, 0, 0.2, 0.6, 1.1, 1.8, 2.6, 3.3, 4.8, 6.3, 7.1, 7.5, 7.6],
      low: 6,
      high: 9,
      heavy: { first: 8, last: 10 },
    },
    why: { base: { kind: 'similar_days', points: Math.round(chance * 100) }, reasons: [] },
    record: null,
    events: [],
  });
  return JSON.stringify({
    schema_version: 1,
    generated_at: '2026-01-12T12:30:00Z',
    directory: STAMP,
    days: [TODAY, '2026-01-13'],
    districts: DISTRICTS.map(([id], district) => {
      const chance = CHANCES[id] ?? null;
      return {
        district,
        time_zone: 'America/Chicago',
        neighbors: [],
        days: [chance === null ? { state: 'no_threat' } : forecast(chance), { state: 'no_threat' }],
      };
    }),
  });
}

function filesIn(folder: string, prefix = ''): string[] {
  return readdirSync(path.join(folder, prefix), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? filesIn(folder, `${prefix}${entry.name}/`) : [`${prefix}${entry.name}`],
  );
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address !== null ? address.port : 0;
      server.close(() => {
        resolve(port);
      });
    });
  });
}

/** Console errors and warnings, page errors and failed or non-2xx requests. */
function watch(page: Page): string[] {
  const problems: string[] = [];
  page.on('console', (message) => {
    const type = message.type();
    const text = message.text();
    if ((type === 'error' || type === 'warning') && !GPU_DRIVER_NOISE.test(text)) {
      if (text !== BLOCKED_WORKER) problems.push(`console.${type}: ${text}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
      problems.push(`requestfailed: ${request.url()}`);
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400)
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
  });
  return problems;
}

/** Stops the page's calendar at `now`, and nothing else (app.spec.ts fixDate). */
async function fixDate(page: Page, now: Date): Promise<void> {
  await page.addInitScript((time: number) => {
    class FixedDate extends Date {
      constructor(...args: unknown[]) {
        super(...((args.length === 0 ? [time] : args) as [number]));
      }

      static override now(): number {
        return time;
      }
    }
    globalThis.Date = FixedDate as unknown as DateConstructor;
  }, now.getTime());
}

/** Resolves once the map is at rest with every tile in. */
async function settleMap(page: Page, timeout = FIRST_FLIGHT_MS): Promise<void> {
  await page.waitForFunction(
    () => {
      const map = window.snowlightMap;
      return map !== undefined && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    },
    null,
    { timeout, polling: 200 },
  );
}

/** Where each school lands on the screen, in CSS pixels. */
async function onScreen(
  page: Page,
  places: readonly { lon: number; lat: number }[],
): Promise<{ x: number; y: number }[]> {
  return page.evaluate((list) => {
    const map = window.snowlightMap;
    if (map === undefined) throw new Error('no map');
    const box = map.getContainer().getBoundingClientRect();
    return list.map(({ lon, lat }) => {
      const point = map.project([lon, lat]);
      return { x: box.left + point.x, y: box.top + point.y };
    });
  }, places);
}

/** The schools around a ZIP code, as the fixture places them. */
function areaSchools(zip: keyof typeof AREAS): School[] {
  const area = AREAS[zip];
  return [...area.own, ...area.near].map(([id]) => SCHOOLS[at(id)]).filter((s) => s !== undefined);
}

/** Every school of the area sits on the map clear of the panel, or above the sheet, and below the field. */
async function expectFramed(page: Page, zip: keyof typeof AREAS): Promise<void> {
  await settleMap(page);
  const panel = await page.locator('aside.detail').boundingBox();
  const bar = await page.locator('header.bar').boundingBox();
  const size = page.viewportSize();
  if (panel === null || bar === null || size === null) throw new Error('no layout');
  const phone = size.width < 720;
  const spots = await onScreen(page, areaSchools(zip));
  for (const spot of spots) {
    expect(spot.y).toBeGreaterThan(bar.y + bar.height);
    expect(spot.x).toBeGreaterThan(phone ? 0 : panel.x + panel.width);
    expect(spot.x).toBeLessThan(size.width);
    expect(spot.y).toBeLessThan(phone ? panel.y : size.height);
  }
}

/**
 * The area's chance as the panel must give it: its students' average, closed or
 * remote as 100%, a district with no weather threat as 0, a school with no chance
 * given left out.
 */
function expectedChance(zip: keyof typeof AREAS): number {
  let students = 0;
  let sum = 0;
  for (const school of areaSchools(zip)) {
    const status = POSTED.find(([id]) => id === school.id)?.[1];
    const district = school.district === null ? null : (DISTRICTS[school.district]?.[0] ?? null);
    const chance =
      status === 0 || status === 2
        ? 1
        : status !== undefined
          ? 0
          : district === null
            ? null
            : (CHANCES[district] ?? 0);
    if (chance === null) continue;
    students += school.students;
    sum += school.students * chance;
  }
  return Math.round((sum / students) * 100);
}

interface Site {
  root: string;
  server: PreviewServer;
  url: string;
}

/** A build with this fixture staged, and with predictions or without, served. */
async function stage(withPredictions: boolean): Promise<Site> {
  const root = mkdtempSync(path.join(tmpdir(), 'snowlight-area-e2e-'));
  const publicDir = path.join(root, 'public');
  for (const file of filesIn(path.join(WEB, 'public'))) {
    if (file.startsWith('data/')) continue;
    mkdirSync(path.dirname(path.join(publicDir, file)), { recursive: true });
    writeFileSync(path.join(publicDir, file), readFileSync(path.join(WEB, 'public', file)));
  }
  const data = path.join(publicDir, 'data');
  for (const folder of ['schools/details', 'schools/areas', 'live', 'predictions']) {
    mkdirSync(path.join(data, folder), { recursive: true });
  }
  const records = path.join(root, 'records.jsonl');
  writeFileSync(records, `${ZIP_RECORDS.join('\n')}\n`);
  execFileSync(
    process.execPath,
    ['scripts/build-search-index.mjs', '--out', path.join(data, 'search-index.bin'), records],
    { cwd: WEB, stdio: 'pipe' },
  );
  writeFileSync(path.join(data, 'schools/meta.json'), meta());
  writeFileSync(path.join(data, 'schools/points.bin'), points());
  const detail = details();
  writeFileSync(path.join(data, 'schools/details/index.json'), detail.index);
  writeFileSync(path.join(data, 'schools/details/0.json'), detail.shard);
  const area = areas();
  writeFileSync(path.join(data, 'schools/areas/index.json'), area.index);
  writeFileSync(path.join(data, 'schools/areas/0.json'), area.shard);
  writeFileSync(path.join(data, 'live/closings.json'), closings());
  if (withPredictions) writeFileSync(path.join(data, 'predictions/latest.json'), predictions());
  const outDir = path.join(root, 'site');
  await build({
    root: WEB,
    publicDir,
    cacheDir: path.join(root, 'vite-cache'),
    logLevel: 'warn',
    build: { outDir, emptyOutDir: true },
  });
  const port = await freePort();
  const server = await preview({
    root: WEB,
    logLevel: 'warn',
    build: { outDir },
    preview: { host: '127.0.0.1', port, strictPort: true },
  });
  return { root, server, url: `http://127.0.0.1:${String(port)}/` };
}

let forecast: Site | undefined;
let calm: Site | undefined;

test.beforeAll(async () => {
  test.setTimeout(300_000);
  if (test.info().project.name !== 'desktop') return;
  forecast = await stage(true);
  calm = await stage(false);
});

test.afterAll(async () => {
  for (const site of [forecast, calm]) {
    await site?.server.close();
    if (site !== undefined) rmSync(site.root, { recursive: true, force: true });
  }
});

/** A page on `site`, its calendar at the fixture's morning, its problems watched. */
async function visit(
  browser: Browser,
  site: Site | undefined,
  options: BrowserContextOptions,
  query = '',
) {
  if (site === undefined) throw new Error('no site');
  const context = await browser.newContext({
    ...options,
    timezoneId: 'America/Chicago',
    serviceWorkers: 'block',
  });
  const page = await context.newPage();
  const problems = watch(page);
  await fixDate(page, NOW);
  await page.goto(`${site.url}${query}`);
  await page.waitForFunction(() => document.querySelector('svg.still') === null, null, {
    timeout: 60_000,
  });
  return { context, page, problems };
}

/** Types a ZIP code into the search field and picks its result. */
async function pickZip(page: Page, zip: string): Promise<void> {
  const input = page.locator('input.search-input');
  await input.click();
  await input.pressSequentially(zip, { delay: 20 });
  const option = page.getByRole('option', { name: new RegExp(zip, 'u') });
  await option.click();
}

const panelOf = (page: Page) => page.locator('aside.detail');

test('a ZIP code picked opens its area beside the map, where the school panel opens, its schools framed clear of it', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, calm, DESKTOP);
  await pickZip(page, '64130');
  await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64130');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-label', 'Schools around 64130');
  await expect(panel).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
  await expect(panel.locator('h2')).toHaveText('64130');
  await expect(panel.locator('.place')).toHaveText('Kansas City, MO');
  await expect(panel.locator('h3.heading')).toHaveText('6 schools');
  await expect(panel.locator('button.school')).toHaveCount(6);
  // The panel takes the focus, as after a pick of a school.
  await expect(panel).toBeFocused();
  // Today's statuses counted over the list, and lit on each row.
  await expect(panel.locator('.counts')).toHaveText('2 closed');
  await expect(panel.locator('button.school .glyph.is-closed')).toHaveCount(2);
  // A screen reader hears each row's status in words, as the light shows it.
  await expect(panel.getByRole('button', { name: /Carver Dual Language/u })).toHaveAccessibleName(
    /\bCarver Dual Language\b.* Closed\b/u,
  );
  await expectFramed(page, '64130');
  const area = await panel.boundingBox();

  // A row opens its school, as a pick of it would, one step on, with a way back.
  const entries = await page.evaluate(() => history.length);
  await panel.getByRole('button', { name: /Carver Dual Language/u }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('school')).toBe('291640000818');
  expect(await page.evaluate(() => history.length)).toBe(entries + 1);
  await expect(panel.locator('h2.name')).toContainText('Carver Dual Language');
  const school = await panel.boundingBox();
  // The same place and width as the school's panel.
  expect(school?.x).toBe(area?.x);
  expect(school?.y).toBe(area?.y);
  expect(school?.width).toBe(area?.width);
  const back = panel.getByRole('button', { name: 'Back to 64130' });
  await back.click();
  await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64130');
  await expect(panel.locator('h2')).toHaveText('64130');
  expect(await page.evaluate(() => history.length)).toBe(entries + 1);
  await expectFramed(page, '64130');
  // Escape closes it.
  await page.locator('body').press('Escape');
  await expect(panel).toHaveCount(0);
  await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBeNull();
  expect(problems).toEqual([]);
  await context.close();
});

test('with no predictions file, as the site is today, there is no chance, no number for one and no word about it', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, calm, DESKTOP, '?zip=64130');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
  await expect(panel.locator('button.school')).toHaveCount(6);
  await expect(panel.locator('.number, .meaning, .why, .chart')).toHaveCount(0);
  const text = await page.locator('body').innerText();
  expect(text).not.toMatch(/enough data|chance|%/iu);
  expect(problems).toEqual([]);
  await context.close();
});

test('with a predictions file, the chance is the students’ average over the counted schools, a closed one 100% and one with no weather threat 0', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, forecast, DESKTOP, '?zip=64130');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
  const expected = expectedChance('64130');
  expect(expected).toBe(62);
  await expect(panel.locator('.number')).toHaveText(`${String(expected)}%`);
  await expect(panel.locator('.meaning')).toContainText('Chance of no school Monday');
  // Who decides, most students first: Kansas City 33 closed both its schools here, so 100%.
  await expect(panel.locator('.why .row .label')).toHaveText(['100%', '40%', '55%', '0%']);
  await expect(panel.locator('.why .row p').first()).toHaveText(
    'Kansas City 33 canceled Monday at 2 schools here.',
  );
  // Genesis has no weather threat today: it counts as no chance at all, and none is left out.
  await expect(panel.locator('.why .row p').last()).toHaveText(
    /^Genesis School\b.* has no weather threat Monday at 1 school here\.$/u,
  );
  await expect(panel.locator('.left')).toHaveCount(0);
  await expect(panel.locator('.chart')).toHaveCount(1);
  // The chart is one district's forecast, of the three here: the one with the most students.
  await expect(panel.locator('.whose')).toHaveText(/^Brookside Charter\b.*’s? forecast$/u);
  await expectFramed(page, '64130');
  expect(problems).toEqual([]);
  await context.close();
});

test('a ZIP code with few schools takes in the nearest others within 2 miles, and says so', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, forecast, DESKTOP, '?zip=64112');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
  await expect(panel.locator('.heading')).toHaveText(['2 schools', '4 more within 2 miles']);
  await expect(panel.locator('button.school .label')).toHaveText([
    '0.1 mi',
    '0.4 mi',
    '0.8 mi',
    '1.1 mi',
    '1.1 mi',
    '1.2 mi',
  ]);
  await expect(panel.locator('button.school').first()).toContainText('Pembroke Hill');
  await expect(panel.locator('.number')).toHaveText(`${String(expectedChance('64112'))}%`);
  await expectFramed(page, '64112');
  expect(problems).toEqual([]);
  await context.close();
});

test('on a phone a ZIP code picked opens in the sheet, half up, its schools framed above it', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, forecast, PHONE);
  await pickZip(page, '64130');
  await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64130');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-busy', 'false', { timeout: 30_000 });
  await expect(panel.locator('h2')).toHaveText('64130');
  await expect(panel.locator('.number')).toHaveText(`${String(expectedChance('64130'))}%`);
  // The sheet opens half up, over the foot of the map.
  await expect
    .poll(async () => {
      const box = await panel.boundingBox();
      const size = page.viewportSize();
      return box === null || size === null ? null : Math.round(size.height - box.y);
    })
    .toBeGreaterThan(300);
  await expectFramed(page, '64130');
  expect(problems).toEqual([]);
  await context.close();
});

test('a ZIP code typed whole opens with Enter, before its result shows or after', async ({
  browser,
}) => {
  const { context, page, problems } = await visit(browser, calm, DESKTOP);
  const input = page.locator('input.search-input');
  // At once, while the search index is still on its way: it opens once search finds it.
  await input.click();
  await input.fill('64112');
  await input.press('Enter');
  await expect
    .poll(() => new URL(page.url()).searchParams.get('zip'), { timeout: 30_000 })
    .toBe('64112');
  const panel = panelOf(page);
  // The panel's code comes once a ZIP code first opens: on a slow machine, after a while.
  await expect(panel.locator('h2')).toHaveText('64112', { timeout: 30_000 });
  await expect(panel).toBeFocused();
  // With its result listed, Enter picks it.
  await input.click();
  await input.fill('');
  await input.pressSequentially('64130', { delay: 20 });
  await expect(page.getByRole('option', { name: /64130/u })).toBeVisible();
  await input.press('Enter');
  await expect.poll(() => new URL(page.url()).searchParams.get('zip')).toBe('64130');
  await expect(panel.locator('h2')).toHaveText('64130');
  // Text that is not a ZIP code opens nothing.
  await input.click();
  await input.fill('6413');
  await input.press('Enter');
  await page.waitForTimeout(1000);
  expect(new URL(page.url()).searchParams.get('zip')).toBe('64130');
  expect(problems).toEqual([]);
  await context.close();
});

test('a link to a ZIP code opens its area and takes in its schools', async ({ browser }) => {
  const { context, page, problems } = await visit(browser, calm, DESKTOP, '?zip=64112');
  const panel = panelOf(page);
  await expect(panel).toHaveAttribute('aria-label', 'Schools around 64112');
  await expect(panel.locator('button.school')).toHaveCount(6);
  await expectFramed(page, '64112');
  // The address keeps the view it took in.
  await expect.poll(() => new URL(page.url()).searchParams.get('at')).not.toBeNull();
  expect(problems).toEqual([]);
  await context.close();
});

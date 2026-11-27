/**
 * The mode switch and Flights mode (flights spec FL-2): switching and Back, the mode kept on the
 * device, deep links to an airport, a route and a flight, the airport panel's answer and FAA
 * line, an old file turning gray with its age, search, the Best time to fly grid, the light
 * theme, a phone's width, and Schools left exactly as it was.
 *
 * The suite's build has no live root, so the flights files are read from the site's own data
 * folder, which these checks answer for: every chance, FAA program, record, usual flight and
 * waiver in them is SYNTHETIC, made up here and living only in this test. The airports are the
 * site's own (public/flights/airports.json).
 */
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

import { BASEMAP_IDS } from '../src/map/basemap/ids';

/** Schools' layers on the shared map (src/modes/schools-layers.ts SCHOOL_LAYER_IDS). */
const SCHOOL_LAYER_IDS = [
  BASEMAP_IDS.glow,
  BASEMAP_IDS.schoolDots,
  BASEMAP_IDS.schoolLight,
  BASEMAP_IDS.schoolSelected,
  BASEMAP_IDS.schoolNames,
  BASEMAP_IDS.schoolSpace,
  'later-rings',
  'later-rings-near',
  'later-rings-close',
];

const ROW = (n: number): number[] => [n, n, n, n, n];

/** The local date in a zone at `at`. */
function localDay(at: Date, zone: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(at);
}

/**
 * The page's clock in the checks that need one: Monday, Jan 5, 2026, 8:00 am in Kansas City
 * (CST), so every block and usual flight before it is over and every one after it is not.
 */
const NOW = new Date('2026-01-05T14:00:00Z');

// The site's service worker, once it controls a page, fetches the flights files itself, past the
// page's routes below: a test that goes to a third address could read the real (empty) host and
// show "could not read". Every test here serves its own files, so no worker takes part.
test.use({ serviceWorkers: 'block' });
const ALL = [0b11111, 0b11111, 0b11111];

interface Files {
  readonly generatedAt: Date;
  /** MCI's cancel chance in every block. */
  readonly mciCancel?: number;
  /** MCI's departure cancel chances by day and block, in place of mciCancel's. */
  readonly mciRows?: (number | null)[][];
  /** MCI's departure chances of a 45+ minute delay by day and block, in place of 6% everywhere. */
  readonly mciLate?: number[][];
  /** Every MCI value the usual rate. */
  readonly mciUsual?: boolean;
  readonly mciWhy?: number[][];
  readonly programs?: unknown[];
  /** LAX's FAA programs. */
  readonly laxPrograms?: unknown[];
  /** More airports in the live file: code, zone and cancel chance in every block. */
  readonly extra?: readonly (readonly [string, string, number])[];
  /** A SkyWest (OO) flight from MCI with a number a bigger airline sells it under. */
  readonly regional?: boolean;
  readonly waivers?: unknown;
  /** When the FAA's programs were read, if not with the rest of the file. */
  readonly programsAt?: Date;
  /** Fields of an airport's live entry by its code, over the made-up ones (JFK is added). */
  readonly over?: Readonly<Record<string, Record<string, unknown>>>;
  /** More records/<code>.json files, by code, beside MCI's. */
  readonly records?: Readonly<Record<string, unknown>>;
  /** More routes/<code>.json files' usual flights, by code, beside MCI's. */
  readonly routes?: Readonly<Record<string, readonly unknown[]>>;
  /** flights/track-record.json. */
  readonly track?: unknown;
}

function airport(code: string, zone: string, cancel: number, made: Date, programs: unknown[] = []) {
  return {
    code,
    today: localDay(made, zone),
    dep_canc: [ROW(cancel), ROW(cancel), ROW(cancel)],
    dep_late: [ROW(60), ROW(60), ROW(60)],
    arr_canc: [ROW(cancel), ROW(cancel), ROW(cancel)],
    arr_late: [ROW(60), ROW(60), ROW(60)],
    rough: [cancel, cancel, cancel],
    runs: [null, null, null],
    usual: [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
    rough_usual: 0,
    why: [[0], [], []],
    programs,
    alerts: [],
    now: null,
  };
}

/** Answers for the flights files the page reads from the site's data folder. */
/** The rows under a Flights answer (LR-F18.2), each as "label | value". */
async function factRows(scope: Locator): Promise<string[]> {
  return scope
    .locator('.fl-fact')
    .evaluateAll((rows) =>
      rows.map(
        (row) =>
          `${row.querySelector('dt')?.textContent.trim() ?? ''} | ${row.querySelector('dd')?.textContent.trim() ?? ''}`,
      ),
    );
}

/** The tags the map's overlay shows now, each with its look (layer.ts writes them on it). */
async function shownTags(page: Page): Promise<[string, string][]> {
  const said = await page
    .locator('canvas.flights-airport-tags')
    .evaluate((node) => (node as HTMLCanvasElement).dataset.tags ?? '')
    .catch(() => '');
  return said
    .split(' ')
    .filter((each) => each !== '')
    .map((each) => each.split(':') as [string, string]);
}

/** Every label layer's visibility and filter, and the place and state names drawn now. */
async function labelState(page: Page): Promise<{ layers: string[]; names: string[] }> {
  return page.evaluate(() => {
    const map = (window as unknown as { snowlightMap?: LabelMap }).snowlightMap;
    if (map === undefined) return { layers: ['no map'], names: [] };
    const labels = map.getStyle().layers.filter((layer) => layer.type === 'symbol');
    const ids = labels.map((layer) => layer.id);
    return {
      layers: ids.map(
        (id) =>
          `${id} ${JSON.stringify(map.getLayoutProperty(id, 'visibility') ?? 'visible')} ${JSON.stringify(map.getFilter(id) ?? null)}`,
      ),
      names: map
        .queryRenderedFeatures({
          layers: ids.filter((id) => /label-(city|town|village|state)|states-in-view/.test(id)),
        })
        .map(
          (feature) =>
            `${feature.layer.id}:${String(feature.properties.name ?? feature.properties.label)}`,
        )
        .sort(),
    };
  });
}

/**
 * The tags the overlay drew at rest, each with its box on the map's canvas, and the map's
 * labels any of them meets, as MapLibre itself hit-tests its placed labels.
 */
async function tagsAndNames(page: Page): Promise<{
  boxes: [string, number, number, number, number][];
  met: string[];
  names: number;
  width: number;
  height: number;
}> {
  return page.evaluate(() => {
    const map = (window as unknown as { snowlightMap?: LabelMap }).snowlightMap;
    const overlay = document.querySelector<HTMLCanvasElement>('canvas.flights-airport-tags');
    if (map === undefined || overlay === null)
      return { boxes: [], met: ['no map'], names: 0, width: 0, height: 0 };
    const boxes = JSON.parse(overlay.dataset.boxes ?? '[]') as [
      string,
      number,
      number,
      number,
      number,
    ][];
    const labels = map
      .getStyle()
      .layers.filter((layer) => layer.type === 'symbol')
      .map((layer) => layer.id);
    const met = boxes.flatMap(([code, x0, y0, x1, y1]) =>
      map
        .queryRenderedFeatures(
          [
            [x0, y0],
            [x1, y1],
          ],
          { layers: labels },
        )
        .map(
          (feature) =>
            `${code} over ${feature.layer.id}:${String(feature.properties.name ?? feature.properties.label)}`,
        ),
    );
    const names = map.queryRenderedFeatures({
      layers: labels.filter((id) => /label-(city|town|village|state)/.test(id)),
    }).length;
    const canvas = map.getCanvas();
    return { boxes, met, names, width: canvas.clientWidth, height: canvas.clientHeight };
  });
}

/** The map as the label checks read it. */
interface LabelMap {
  getStyle(): { layers: { id: string; type: string }[] };
  getLayoutProperty(id: string, name: string): unknown;
  getFilter(id: string): unknown;
  queryRenderedFeatures(
    geometry: [[number, number], [number, number]] | { layers: string[] },
    options?: { layers: string[] },
  ): { layer: { id: string }; properties: Record<string, unknown> }[];
  getCanvas(): HTMLCanvasElement;
}

async function serveFlights(page: Page, files: Files): Promise<void> {
  const made = files.generatedAt;
  const stamp = `${made.toISOString().slice(0, 16).replace(/[-:]/g, '')}Z`;
  const at = made.toISOString().replace(/\.\d+Z$/, 'Z');
  const live = {
    schema_version: 1,
    generated_at: at,
    slot: 'slot-1',
    stamp,
    run: at,
    programs_at:
      files.programsAt === undefined ? at : files.programsAt.toISOString().replace(/\.\d+Z$/, 'Z'),
    alerts_at: at,
    weather_at: at,
    observed_at: at,
    airports: [
      {
        ...airport('MCI', 'America/Chicago', files.mciCancel ?? 200, made, files.programs ?? []),
        ...(files.mciRows === undefined ? {} : { dep_canc: files.mciRows }),
        ...(files.mciLate === undefined ? {} : { dep_late: files.mciLate }),
        ...(files.mciUsual === true ? { usual: [ALL, ALL, ALL, ALL], rough_usual: 7 } : {}),
        ...(files.mciWhy === undefined ? {} : { why: files.mciWhy }),
      },
      airport('LAX', 'America/Los_Angeles', 10, made, files.laxPrograms ?? []),
      airport('DEN', 'America/Denver', 10, made),
      ...(files.over?.JFK === undefined ? [] : [airport('JFK', 'America/New_York', 3, made)]),
      ...(files.extra ?? []).map(([code, zone, cancel]) => airport(code, zone, cancel, made)),
    ].map((entry) => ({ ...entry, ...(files.over?.[entry.code] ?? {}) })),
  };
  const routes = {
    schema_version: 1,
    generated_at: at,
    code: 'MCI',
    months: [
      {
        month: '2026-09',
        flights: [
          // Every day, in the morning and the evening (MCI's clock), landing on LAX's.
          {
            carrier: 'WN',
            number: 1234,
            to_airport: 'LAX',
            leaves: 600,
            lands: 720,
            weekdays: 127,
            days: 30,
            cancelled: 0,
            late: 2,
          },
          // The same flight number twice in a month, as BTS lists a changed schedule.
          {
            carrier: 'WN',
            number: 1234,
            to_airport: 'LAX',
            leaves: 615,
            lands: 735,
            weekdays: 96,
            days: 8,
            cancelled: 0,
            late: 1,
          },
          ...(files.regional === true
            ? [
                {
                  carrier: 'OO',
                  number: 5489,
                  to_airport: 'LAX',
                  leaves: 1220,
                  lands: 1340,
                  weekdays: 127,
                  days: 30,
                  cancelled: 0,
                  late: 2,
                },
              ]
            : []),
          {
            carrier: 'AA',
            number: 88,
            to_airport: 'LAX',
            leaves: 1080,
            lands: 1200,
            weekdays: 127,
            days: 30,
            cancelled: 1,
            late: 3,
          },
        ],
      },
    ],
  };
  const record = {
    schema_version: 1,
    generated_at: at,
    code: 'MCI',
    first: '2015-01-01',
    last: '2026-09-30',
    lines: [
      {
        kind: 2,
        blocks: 300,
        bad: 77,
        days: 160,
        bad_days: 42,
        share: 99,
        others: 50,
        worse: 40,
        better: 5,
        verdict: 2,
      },
    ],
    carriers: [],
  };
  const routesOf = (code: string): unknown => {
    const flights = files.routes?.[code];
    return flights === undefined
      ? null
      : { ...routes, code, months: [{ month: '2026-09', flights }] };
  };
  await page.route('**/data/flights/**', async (route) => {
    const url = new URL(route.request().url());
    const name = url.pathname.replace(/^.*\/data\/flights\//, '');
    const body =
      name === 'latest.json'
        ? { schema_version: 1, generated_at: at, slot: 'slot-1', stamp }
        : name === 'live/slot-1.json'
          ? live
          : name === 'routes/mci.json'
            ? routes
            : name === 'records/mci.json'
              ? record
              : name === 'waivers.json' && files.waivers !== undefined
                ? files.waivers
                : name === 'track-record.json' && files.track !== undefined
                  ? files.track
                  : (files.records?.[name.replace(/^records\/(\w+)\.json$/, '$1').toUpperCase()] ??
                    routesOf(name.replace(/^routes\/(\w+)\.json$/, '$1').toUpperCase()));
    if (body === null) await route.fulfill({ status: 404, body: '' });
    else
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
  });
}

async function switchTo(page: Page, name: 'Schools' | 'Flights'): Promise<void> {
  await page.getByRole('radio', { name }).click();
}

/** Schools as a fresh load shows it: its search, menu, key and the switch, and nothing of Flights. */
async function expectSchoolsWhole(page: Page): Promise<void> {
  await expect(page.locator('.stage > .legend')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Search a school, city, or ZIP' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Menu', exact: true })).toBeVisible();
  await expect(page.getByRole('radiogroup', { name: 'Show' })).toBeVisible();
  await expect(page.getByRole('radio', { name: 'Schools' })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  await expect(page.locator('.mode-ui')).toHaveCount(0);
  await expect(page.locator('.fl-head')).toHaveCount(0);
  await expect(
    page.getByRole('list', { name: 'Chance of cancels and long delays today' }),
  ).toHaveCount(0);
  await expect(page.getByText('We could not read the flight chances just now.')).toHaveCount(0);
  expect(
    await page.evaluate(() =>
      [...document.querySelectorAll('header.bar > *')].map(
        (node) => node.className.split(' ')[0] ?? '',
      ),
    ),
  ).toEqual(['wordmark', 'search', 'menu-button', 'mode-switch']);
}

test.describe.configure({ timeout: 120_000 });

test('switches between Schools and Flights, with Back, and keeps the mode on the device', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/');
  const switcher = page.getByRole('radiogroup', { name: 'Show' });
  await expect(switcher).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('radio', { name: 'Schools' })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  const schoolsKey = page.locator('.stage > .legend');
  await expect(schoolsKey).toBeVisible();

  await switchTo(page, 'Flights');
  await expect(page).toHaveURL(/[?&]mode=flights/);
  await expect(
    page.getByRole('list', { name: 'Chance of cancels and long delays today' }),
  ).toBeVisible();
  await expect(schoolsKey).toBeHidden();
  await expect(
    page.getByRole('combobox', { name: 'Search an airport, flight or route' }),
  ).toBeVisible();
  await expect(page.getByRole('combobox', { name: /Search a school/ })).toBeHidden();

  await page.goBack();
  await expect(page).not.toHaveURL(/mode=/);
  await expectSchoolsWhole(page);
  await page.goForward();
  await expect(page).toHaveURL(/mode=flights/);
  await expect(schoolsKey).toBeHidden();
  // And back by the switch: Schools whole again.
  await switchTo(page, 'Schools');
  await expectSchoolsWhole(page);

  // Kept on this device: the bare address opens on the mode last picked, and says so.
  await switchTo(page, 'Flights');
  await expect(page).toHaveURL(/mode=flights/);
  await page.goto('/');
  await expect(page).toHaveURL(/mode=flights/, { timeout: 60_000 });
  await expect(page.getByRole('radio', { name: 'Flights' })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  // An old link to a school still opens Schools.
  await page.goto('/?at=39.1,-94.6,9');
  await expect(page.getByRole('radio', { name: 'Schools' })).toHaveAttribute(
    'aria-checked',
    'true',
    {
      timeout: 60_000,
    },
  );

  // The keyboard: the arrows move between the modes.
  await page.getByRole('radio', { name: 'Schools' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('radio', { name: 'Flights' })).toBeFocused();
  await expect(page).toHaveURL(/mode=flights/);
});

test('opens an airport from a link: the answer first, the day by block, the FAA and the record', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programs: [
      { program: 2, minutes: 30, until: null, why: 2 },
      { program: 0, minutes: null, until: null, why: 1 },
    ],
  });
  await page.goto('/?mode=flights&airport=MCI');
  const answer = page.getByTestId('flights-answer');
  // Schools' chance look (LR-F9): the number, what it is, then one block of rows (LR-F18.2).
  // Every usual flight left today has a 20% chance, so the day's number is 20.
  await expect(answer.locator('.fl-hero-number')).toHaveText('20%', { timeout: 60_000 });
  await expect(answer.locator('.fl-hero-meaning')).toHaveText('20% Chance of a cancel today');
  // The reason, the live FAA program, then the late chance, each a label and its value.
  await expect
    .poll(() => factRows(answer))
    .toEqual([
      'Why | Snow in the forecast',
      'FAA | Ground stop now, not counted',
      'Delay of 45+ min | 6%',
    ]);
  // No callout, no level sentence, no "up to", no code the title shows already.
  await expect(answer).not.toContainText(/risk|up to|MCI/);
  expect(await answer.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(
    'rgba(0, 0, 0, 0)',
  );
  await expect(answer).not.toHaveClass(/is-old/);
  await expect(page.getByTestId('flights-blocks')).toContainText('20%');
  // 8 am: the early block (5 to 9 am) still runs, so none is over. The third day by its name.
  await expect(page.getByTestId('flights-blocks')).not.toContainText('Over');
  await expect(page.getByRole('group', { name: 'Day' })).toContainText('Wednesday');
  // A screen reader reads each block with its hours and both of its values, each with the level
  // its bar shows in words (TRAV-R11-S3).
  await expect(page.getByRole('listitem').filter({ hasText: 'Morning, 9 am to noon.' })).toHaveText(
    'Morning, 9 am to noon. Cancel: 20%, high risk. 45+ min late: 6%, low risk.',
  );
  // The ground stop listed after the delay is shown first, never hidden.
  await expect(page.getByTestId('flights-faa').locator('.fl-text').first()).toContainText(
    'Ground stop',
  );
  await expect(page.getByTestId('flights-faa')).toContainText('Ground stop');
  await expect(page.getByTestId('flights-faa')).toContainText('Because of weather.');
  await expect(page.getByTestId('flights-record')).toContainText('Snow: Cancels sooner than most');
  // No waivers file: every waiver line is not checked, never none found.
  await expect(page.getByTestId('flights-waivers')).toContainText('We could not check');
  await expect(page.locator('.fl-updated')).toHaveText('Updated 5 min ago');
});

test('grays an old file with its age and never shows its FAA line as live', async ({ page }) => {
  await serveFlights(page, {
    generatedAt: new Date(Date.now() - 3 * 3_600_000),
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&airport=MCI');
  const answer = page.getByTestId('flights-answer');
  await expect(answer).toHaveClass(/is-old/, { timeout: 60_000 });
  await expect(answer).toContainText('Old: from 3 h ago');
  // An old file names its days by their dates, never as today, and gives no number or level.
  await expect(page.getByRole('group', { name: 'Day' })).not.toContainText('Today');
  await expect(answer).not.toContainText('risk');
  await expect(answer.locator('.fl-hero-number')).toHaveCount(0);
  // Its reasons are its own, never now's: in gray, with the file's age, never "No storm".
  const why = page.getByRole('region', { name: 'Why' });
  await expect(why).toContainText('Snow in the forecast');
  await expect(page.getByTestId('flights-why-old')).toHaveText('Old: from 3 h ago');
  await expect(why).not.toContainText('No storm in the forecast');
  await expect(why.locator('.fl-text')).toHaveCount(0);
  // Its FAA read is what it said then, in gray with its age, never as now and never lost.
  await expect(answer).not.toContainText('Ground stop');
  await expect(page.getByTestId('flights-faa-old')).toHaveText('Ground stop');
  await expect(page.getByTestId('flights-faa')).toContainText('FAA status from 3 h ago');
  await expect(page.getByTestId('flights-faa')).not.toContainText('could not read');
  // The key goes gray with the map's tags, never naming a risk the map does not show.
  const key = page.locator('.flights-legend');
  await expect(key).toHaveClass(/is-old/);
  await expect(key).toHaveAttribute('aria-label', 'The map is old, so it shows no risk now.');
});

test('searches a route and shows Best time to fly, then a flight from it', async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    // Tomorrow morning is the safest; the evenings the worst.
    mciRows: [
      [30, 30, 30, 80, 30],
      [20, 20, 20, 80, 20],
      [40, 40, 40, 80, 40],
    ],
  });
  await page.goto('/?mode=flights');
  const field = page.getByRole('combobox', { name: 'Search an airport, flight or route' });
  await expect(field).toBeVisible({ timeout: 60_000 });
  await field.fill('MCI to LAX');
  await expect(page.getByRole('option', { name: /MCI to LAX/ })).toBeVisible();
  // Picked from the keyboard: the panel takes the focus, as Schools' does.
  await field.press('Enter');
  await expect(page).toHaveURL(/route=MCI-LAX/);
  await expect(page.locator('.mode-ui .detail')).toBeFocused();
  const grid = page.getByTestId('flights-grid');
  await expect(grid).toBeVisible();
  // Three days by five blocks: the usual flights fly in the morning and the evening only.
  await expect(grid.locator('.fl-cell')).toHaveCount(15);
  await expect(grid.locator('button.fl-cell')).toHaveCount(6);
  const best = page.getByTestId('flights-best');
  await expect(best.locator('.fl-hero-number')).toHaveText('3%');
  await expect(best.locator('.fl-hero-meaning')).toHaveText(
    '3% Chance of a cancel tomorrow, 9 am to noon. It is the safest time to fly.',
  );
  // An empty cell says why, to a screen reader and on the screen.
  const empty = grid.getByRole('img', { name: 'Today, Early: No usual flights' });
  await expect(empty).toHaveCount(1);
  await expect(empty).toHaveText('No flights');

  // Pressed from the keyboard: on a phone the sheet grows as its rows come into view.
  const row = page.getByRole('button', { name: /WN 1234/ }).first();
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/flight=WN1234-MCI/);
  await expect(page.getByTestId('flights-card')).toContainText('MCI');
  await expect(page.getByTestId('flights-card')).toContainText('LAX');
  await expect(page.getByTestId('flights-card')).toContainText('10:00 am');
  // Its own past storm days are not in the files yet: said plainly, the airport's record below.
  await expect(page.getByTestId('flights-record')).toContainText(
    'We do not have this flight on past storm days yet.',
  );
  // The airline's waiver, once for the trip (it is the airline's), not checked with no file.
  const waiver = page.getByTestId('flights-waivers');
  await expect(waiver).toContainText('We could not check Southwest’s page just now.');
  expect(await waiver.locator('p.fl-small').count()).toBe(1);
  await expect(page.getByTestId('flights-end')).not.toContainText(['Southwest’s page']);

  // A flight number with the airport typed after it.
  await field.fill('AA 88 MCI');
  await page.getByRole('option', { name: /AA 88/ }).click();
  await expect(page).toHaveURL(/flight=AA88-MCI/);
});

test('says the usual rate as the usual rate, never as a level, under a storm and a stop', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  const made = new Date(NOW.getTime() - 10 * 60_000).toISOString().replace(/\.\d+Z$/, 'Z');
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciCancel: 10,
    mciUsual: true,
    mciWhy: [[0], [0], []],
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
    waivers: {
      schema_version: 1,
      generated_at: made,
      airlines: [
        { code: 'WN', name: 'Southwest', path: '/alerts', state: 'checked', read_at: made },
        { code: 'AA', name: 'American', path: '/alerts', state: 'not_checked', read_at: null },
      ],
      waivers: [
        {
          airline: 'WN',
          airports: null,
          all_airports: false,
          travel_from: '2026-01-04',
          travel_to: '2026-01-07',
          unclear_days: [],
          on_page: true,
          active: true,
          last_seen: made,
        },
      ],
    },
  });
  await page.goto('/?mode=flights&airport=MCI');
  const answer = page.getByTestId('flights-answer');
  // Monday, Jan 5, 2026: the usual rate as itself, never as a forecast or a level.
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    '1% Usual chance of a cancel on a Monday',
    { timeout: 60_000 },
  );
  const usualRows = await factRows(answer);
  expect(usualRows).toContain('Forecast | None for this day yet');
  await expect(answer).not.toContainText('risk');
  expect(usualRows.filter((row) => row.startsWith('Why | '))).toEqual([]);
  expect(usualRows).toContain('Left out | Weather and the FAA');
  expect(usualRows).toContain('Usual rate | Both chances');
  // One Forecast row, never two.
  expect(usualRows.filter((row) => row.startsWith('Forecast | '))).toHaveLength(1);
  // A waiver that names no airports plainly is unclear; an airline not read is not checked.
  const waivers = page.getByTestId('flights-waivers');
  await expect(waivers).toContainText('We could not tell if it covers this trip.');
  await expect(waivers).toContainText('We could not check American’s page just now.');
  await expect(waivers).not.toContainText('no waiver');
});

/** JFK's cancels the usual rate and its late chances the forecast's, as on Nov 26, 2026. */
const CANCEL_USUAL = [ALL, [0, 0, 0], ALL, [0, 0, 0]];
/** A record with one strong wind line (SYNTHETIC numbers in the shape of JFK's). */
function windRecord(code: string, days: number, badDays: number) {
  return {
    schema_version: 1,
    generated_at: '2026-11-22T14:11:48Z',
    code,
    first: '2020-01-31',
    last: '2026-09-30',
    lines: [
      {
        kind: 5,
        blocks: 87,
        bad: 15,
        days,
        bad_days: badDays,
        share: 48,
        others: 66,
        worse: 0,
        better: 0,
        verdict: 0,
      },
    ],
    carriers: [],
  };
}

test('says a usual cancel chance as usual on a windy day, with what past windy days did here', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    over: { JFK: { usual: CANCEL_USUAL, why: [[3], [3], []] } },
    records: { JFK: windRecord('JFK', 60, 12) },
  });
  await page.goto('/?mode=flights&airport=JFK');
  const answer = page.getByTestId('flights-answer');
  // The cancel number is the usual rate: said so, though the late chance is the forecast's,
  // and over the blocks left today, as the day number is.
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    '<1% Usual chance of a cancel for the rest of today',
    { timeout: 60_000 },
  );
  // No "Why" under the usual headline: the one usual rule (LR-SF8) names the cancel chance as
  // the usual rate and what it leaves out, then the forecast's wind as the weather; the share is
  // of the windy hours, never whole days; and the record's bad days are never said.
  await expect
    .poll(() => factRows(answer))
    .toEqual([
      'Delay of 45+ min | 6%',
      'Usual rate | Cancel chance',
      'Left out | Weather and the FAA',
      'Weather | Strong wind in the forecast',
      'Windy days here | 60 since 2020',
      'Cancelled here | 5% in the wind',
      'Elsewhere | 7% in the same weather',
    ]);
  // The reasons below are the forecast's weather, never headed as why the usual rate is.
  await expect(page.getByTestId('flights-why').locator('h3')).toHaveText('In the forecast');
  // The table's note says the usual rate is in place of the forecast, never that it is not ready.
  await expect(page.locator('.fl-usual-note').first()).toHaveText(
    'Usual means the usual rate for this time of year, in place of our forecast.',
  );
  await expect(answer).not.toContainText('risk');
});

test('says no past days beside a forecast cancel chance, even where the late chance is usual', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    over: { JFK: { usual: [[0, 0, 0], ALL, [0, 0, 0], ALL], why: [[3], [3], []] } },
    records: { JFK: windRecord('JFK', 60, 12) },
  });
  await page.goto('/?mode=flights&airport=JFK');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    '<1% Chance of a cancel for the rest of today',
    { timeout: 60_000 },
  );
  // The same two rows by value (LR-SF8): the delay chance is the usual rate, never the forecast
  // cancel chance; the wind is said as the weather, never as "Why" beside a usual number.
  await expect.poll(() => factRows(answer)).toContain('Usual rate | Delay chance');
  const said = await factRows(answer);
  expect(said).toContain('Left out | Weather and the FAA');
  expect(said).toContain('Weather | Strong wind in the forecast');
  expect(said.filter((row) => row.startsWith('Why | '))).toEqual([]);
  await expect(answer).not.toContainText(' since 2020');
  await expect(page.getByTestId('flights-why').locator('h3')).toHaveText('In the forecast');
});

test('names the weather the record rows speak to, though another reason comes first', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // Cold first, then strong wind (SYNTHETIC order: the file lists weather kinds first).
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    over: { JFK: { usual: CANCEL_USUAL, why: [[5, 3], [3], []] } },
    records: { JFK: windRecord('JFK', 60, 12) },
  });
  await page.goto('/?mode=flights&airport=JFK');
  const answer = page.getByTestId('flights-answer');
  await expect
    .poll(() => factRows(answer), { timeout: 60_000 })
    .toContain('Windy days here | 60 since 2020');
  const said = await factRows(answer);
  expect(said.filter((row) => row.startsWith('Weather | '))).toEqual([
    'Weather | Strong wind in the forecast',
  ]);
});

test('says no past days on a flight whose cancel chance is the forecast’s at one end', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[], [], []],
    // LAX's arrival cancels the usual rate, with strong wind in its forecast.
    over: {
      LAX: { usual: [[0, 0, 0], [0, 0, 0], ALL, [0, 0, 0]], why: [[3], [], []] },
    },
    records: { LAX: windRecord('LAX', 35, 0) },
  });
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const answer = page.getByTestId('flights-answer');
  // MCI's cancel chance is a forecast: the flight's number is not the usual rate as a whole.
  await expect(answer.locator('.fl-hero-meaning')).toHaveText('21% Chance of a cancel today', {
    timeout: 60_000,
  });
  // Its headline reads as a forecast, as the airport's does with a forecast cancel: no record
  // rows, which would say past weather the rows above do not. The cancel number is LAX's usual
  // rate in part, so LAX's wind is said as the weather, never as "Why" (LR-SF8).
  await expect.poll(() => factRows(answer)).toContain('Usual rate | Part of the cancel chance');
  const said = await factRows(answer);
  expect(said).toContain('Left out | Weather and the FAA');
  expect(said).toContain('At LAX | Strong wind in the forecast');
  expect(said.filter((row) => row.startsWith('Why | '))).toEqual([]);
  expect(said.filter((row) => /^(\w+ days (here|at )|Cancelled|Elsewhere)/u.test(row))).toEqual([]);
});

test('says a flight whose cancels are usual at both ends as usual, beside forecast late chances', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // JFK to PHL on Nov 26 in shape: each end's cancels the usual rate, its late chances the
  // forecast's, strong wind in the landing airport's forecast.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[], [], []],
    over: { MCI: { usual: CANCEL_USUAL }, LAX: { usual: CANCEL_USUAL, why: [[3], [], []] } },
    records: { LAX: windRecord('LAX', 35, 4) },
  });
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    /^\d+% Usual chance of a cancel on a Monday$/u,
    { timeout: 60_000 },
  );
  await expect.poll(() => factRows(answer)).toContain('Windy days at LAX | 35 since 2020');
  const said = await factRows(answer);
  // The forecast's wind never as the reason for the usual cancel chance, and neither end is
  // said as not ready: both forecasts are there, their late chances shown.
  expect(said.filter((row) => row.startsWith('Why | '))).toEqual([]);
  expect(said.filter((row) => row.includes('Not ready'))).toEqual([]);
  expect(said).toContain('Usual rate | Cancel chance');
  expect(said).toContain('Left out | Weather and the FAA');
  // The weather the record rows speak to, at the airport they are for.
  expect(said).toContain('At LAX | Strong wind in the forecast');
  expect(said.indexOf('At LAX | Strong wind in the forecast')).toBeLessThan(
    said.indexOf('Windy days at LAX | 35 since 2020'),
  );
  expect(said).toContain('Cancelled at LAX | 5% in the wind');
  expect(said.filter((row) => row.startsWith('Delay of 45+ min | '))).toHaveLength(1);
  await expect(answer).not.toContainText('risk');
});

/** JFK and PHL on the host file: cancels usual at both ends, the landing end's late usual too. */
const HOST_SHAPE = [ALL, [0, 0, 0], ALL, ALL];
/** A run read for each day, as on the host file (a forecast is there, its test failed). */
const RUNS = ['2026-01-05T00:00:00Z', '2026-01-05T00:00:00Z', '2026-01-05T00:00:00Z'];

/** The rows' words LR-SF8 ended: half forms and per-combination values. */
const HALF_FORMS =
  /weather left out|Usual rate in part|The usual rate|Part of this chance|Not ready.*\n.*None/u;

test('marks a flight’s delay as usual where the larger end’s late value is the usual rate', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // The delay is the larger of the two ends': here LAX's usual 9%, over MCI's forecast 4%, so the
  // number shown is wholly the usual rate (LR-SF8 rule 1).
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[], [], []],
    over: {
      MCI: { usual: HOST_SHAPE, runs: RUNS, dep_late: [ROW(40), ROW(40), ROW(40)] },
      LAX: {
        usual: HOST_SHAPE,
        runs: RUNS,
        arr_late: [ROW(91), ROW(91), ROW(91)],
        why: [[3], [], []],
      },
    },
    records: { LAX: windRecord('LAX', 35, 4) },
  });
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    /^\d+% Usual chance of a cancel on a Monday$/u,
    { timeout: 60_000 },
  );
  await expect.poll(() => factRows(answer)).toContain('Delay of 45+ min | 9%');
  const said = await factRows(answer);
  // One row names both numbers as the usual rate, one says what they leave out.
  expect(said.filter((row) => /^(Usual rate|Left out) \| /u.test(row))).toEqual([
    'Usual rate | Both chances',
    'Left out | Weather and the FAA',
  ]);
  expect(said.join('\n')).not.toMatch(HALF_FORMS);
  expect(said.filter((row) => row.startsWith('Why | '))).toEqual([]);
  // Both forecasts were read: neither end is said as not ready.
  expect(said.filter((row) => row.startsWith('Forecast | '))).toEqual([]);
});

/** JFK on the host file: cancels usual, its departure late chance the forecast's, arr_late usual. */
const JFK_HOST = { usual: HOST_SHAPE, runs: RUNS, dep_late: [ROW(86), ROW(86), ROW(86)] };
/** JFK's usual flights for the flight and route tests: to BOS, and to LAX in SEA's place. */
const JFK_FLIGHTS = [
  {
    carrier: 'B6',
    number: 1015,
    to_airport: 'BOS',
    leaves: 960,
    lands: 1035,
    weekdays: 127,
    days: 30,
    cancelled: 0,
    late: 2,
  },
];

test('marks JFK to BOS’s delay as usual, BOS’s usual arrival rate over JFK’s forecast', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    extra: [['BOS', 'America/New_York', 3]],
    over: {
      JFK: { ...JFK_HOST, why: [[3], [3], []] },
      BOS: { usual: HOST_SHAPE, runs: RUNS, arr_late: [ROW(91), ROW(91), ROW(91)] },
    },
    records: { JFK: windRecord('JFK', 60, 12) },
    routes: { JFK: JFK_FLIGHTS },
  });
  await page.goto('/?mode=flights&flight=B61015-JFK');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-meaning')).toHaveText(
    /^\d+% Usual chance of a cancel on a Monday$/u,
    { timeout: 60_000 },
  );
  await expect.poll(() => factRows(answer)).toContain('Windy days at JFK | 60 since 2020');
  const said = await factRows(answer);
  expect(said).toContain('Delay of 45+ min | 9%');
  expect(said.filter((row) => /^(Usual rate|Left out) \| /u.test(row))).toEqual([
    'Usual rate | Both chances',
    'Left out | Weather and the FAA',
  ]);
  expect(said).toContain('At JFK | Strong wind in the forecast');
  expect(said.join('\n')).not.toMatch(HALF_FORMS);
  expect(said.filter((row) => row.startsWith('Why | '))).toEqual([]);
  await expect(answer).not.toContainText('risk');
});

/** Every label and value under the answer on one line (LR-F18 uniform rows). */
async function rowLines(scope: Locator): Promise<string[]> {
  return scope.locator('.fl-fact').evaluateAll((rows) =>
    rows.flatMap((row) => {
      const cells = [row.querySelector('dt'), row.querySelector('dd')];
      return cells.flatMap((cell) => {
        if (cell === null) return [];
        const line = Number.parseFloat(getComputedStyle(cell).lineHeight);
        const lines = Math.round(cell.getBoundingClientRect().height / line);
        return lines === 1 ? [] : [`${cell.textContent.trim()} (${String(lines)} lines)`];
      });
    }),
  );
}

// Each kind of weather the record speaks to: reason, record kind and its rows' words.
for (const [why, kind, name] of [
  [3, 5, 'wind'],
  [1, 1, 'ice'],
  [2, 3, 'thunder'],
  [4, 4, 'fog'],
  [0, 2, 'snow'],
] as const) {
  test(`keeps every row on one line at 360 px beside a usual cancel chance, ${name}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.clock.setFixedTime(NOW);
    const record = (code: string) => {
      // The longest values a row can carry: four figures of days, and "Under 1%" twice.
      const r = windRecord(code, 1112, 0);
      return { ...r, lines: r.lines.map((line) => ({ ...line, kind, share: 4, others: 4 })) };
    };
    // The airport: JFK's shape, its late chances the forecast's.
    await serveFlights(page, {
      generatedAt: new Date(NOW.getTime() - 5 * 60_000),
      over: { JFK: { usual: CANCEL_USUAL, why: [[why], [why], []] } },
      records: { JFK: record('JFK') },
    });
    await page.goto('/?mode=flights&airport=JFK');
    const answer = page.getByTestId('flights-answer');
    await expect
      .poll(() => factRows(answer), { timeout: 60_000 })
      .toContainEqual(expect.stringMatching(/^[\w ]+ days here \| 1112 since/u));
    expect(await factRows(answer)).toContain('Usual rate | Cancel chance');
    expect(await rowLines(answer)).toEqual([]);
    // The flight, both ends' cancels usual: as forecast lates, and as on the host file.
    // The flight: both ends' cancels usual, as forecast lates and as on the host file, with the
    // FAA's longest row at both ends; and the longest usual row, a cancel chance usual in part.
    const departures = [{ program: 2, minutes: 60, until: null, why: 2 }];
    const flights = [
      { mci: CANCEL_USUAL, lax: CANCEL_USUAL, faa: false, which: 'Cancel chance' },
      { mci: HOST_SHAPE, lax: HOST_SHAPE, faa: true, which: 'Both chances' },
      {
        mci: HOST_SHAPE,
        lax: [[0, 0, 0], [0, 0, 0], [0, 0, 0], ALL],
        faa: false,
        which: 'Delay chance, part of cancel',
      },
    ];
    for (const { mci, lax, faa, which } of flights) {
      await page.unroute('**/data/flights/**');
      await serveFlights(page, {
        generatedAt: new Date(NOW.getTime() - 5 * 60_000),
        mciWhy: [[], [], []],
        ...(faa ? { programs: departures, laxPrograms: departures } : {}),
        over: {
          MCI: { usual: mci, runs: RUNS },
          LAX: {
            usual: lax,
            runs: RUNS,
            why: [[why], [], []],
            arr_late: [ROW(91), ROW(91), ROW(91)],
          },
        },
        records: { LAX: record('LAX') },
      });
      await page.goto('/?mode=flights&flight=WN1234-MCI');
      await expect
        .poll(() => factRows(answer), { timeout: 60_000 })
        .toContain(`Usual rate | ${which}`);
      const said = await factRows(answer);
      expect(said).toContain('Left out | Weather and the FAA');
      if (lax === CANCEL_USUAL || lax === HOST_SHAPE)
        expect(said).toContainEqual(expect.stringMatching(/^[\w ]+ days at LAX \| 1112 since/u));
      if (faa)
        expect(
          said.filter((row) => /^FAA at (MCI|LAX) \| Departures late now, not counted$/u.test(row)),
        ).toHaveLength(2);
      expect(await rowLines(answer)).toEqual([]);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
  });
}

test('draws no level on a route time whose cancels are usual at both ends, and ranks none', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // A forecast late chance of 32% at both ends, which alone would make a level.
  const late = [ROW(320), ROW(320), ROW(320)];
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[], [], []],
    over: {
      MCI: { usual: CANCEL_USUAL, dep_late: late, arr_late: late },
      LAX: { usual: CANCEL_USUAL, dep_late: late, arr_late: late },
    },
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const grid = page.getByTestId('flights-grid');
  await expect(grid.locator('button.fl-cell').first()).toBeVisible({ timeout: 60_000 });
  const levels = await grid
    .locator('button.fl-cell')
    .evaluateAll((cells) => cells.map((cell) => cell.getAttribute('data-level')));
  expect(levels.length).toBeGreaterThan(0);
  expect(levels.filter((level) => level !== null)).toEqual([]);
  const labels = await grid
    .locator('button.fl-cell')
    .evaluateAll((cells) => cells.map((cell) => cell.getAttribute('aria-label') ?? ''));
  expect(labels.filter((label) => !label.endsWith('chance of a cancel, usual'))).toEqual([]);
  // The late chances are the forecast's: the one rule names the cancel chance alone.
  const best = page.getByTestId('flights-best');
  await expect(best.locator('.fl-hero-meaning')).toHaveText(
    'The usual rate is in each chance here, so none of these times stands out.',
  );
  expect(await factRows(best)).toEqual([
    'Usual rate | Cancel chance',
    'Left out | Weather and the FAA',
  ]);
});

/** A route grid's cells as drawn: each cell's level, usual mark and label, and its first pill. */
async function routeCells(page: Page): Promise<{
  levels: (string | null)[];
  usual: boolean[];
  labels: string[];
  pill: string;
}> {
  const grid = page.getByTestId('flights-grid');
  await expect(grid.locator('button.fl-cell').first()).toBeVisible({ timeout: 60_000 });
  const cells = grid.locator('button.fl-cell');
  const levels = await cells.evaluateAll((all) =>
    all.map((cell) => cell.getAttribute('data-level')),
  );
  const usual = await cells.evaluateAll((all) =>
    all.map((cell) => cell.classList.contains('is-usual')),
  );
  const labels = await cells.evaluateAll((all) =>
    all.map((cell) => cell.getAttribute('aria-label') ?? ''),
  );
  await cells.first().click();
  const pill = page.locator('.fl-pill').first();
  await expect(pill).toBeVisible();
  return { levels, usual, labels, pill: (await pill.textContent())?.trim() ?? '' };
}

test('never marks a route’s forecast cancel chance usual for a usual late chance (PIT to SNA)', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // The host file's pattern: cancels the model's at both ends, the arrival's late chance usual.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[], [], []],
    over: {
      MCI: { usual: [[0, 0, 0], [0, 0, 0], [0, 0, 0], ALL], runs: RUNS },
      LAX: {
        usual: [[0, 0, 0], [0, 0, 0], [0, 0, 0], ALL],
        runs: RUNS,
        arr_late: [ROW(91), ROW(91), ROW(91)],
      },
    },
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const { usual, labels, pill } = await routeCells(page);
  // The cancel number is wholly the forecast's: no usual mark, never "Usual rate".
  expect(usual.filter(Boolean)).toEqual([]);
  expect(labels.filter((label) => label.includes('usual'))).toEqual([]);
  expect(pill).toMatch(/^Cancel chance \d+%\.$/u);
  // The delay chance is the usual rate, which never ranks one time over another: said by value.
  const best = page.getByTestId('flights-best');
  expect(await factRows(best)).toEqual([
    'Usual rate | Delay chance',
    'Left out | Weather and the FAA',
  ]);
});

test('marks a route’s cancel chance usual in part where one end’s is (JFK to SEA on a windy day)', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  // JFK in MCI's place: cancels usual, a 30% forecast late chance; LAX in SEA's: the model's
  // cancels, its arrival late chance usual.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[3], [3], []],
    over: {
      MCI: { usual: HOST_SHAPE, runs: RUNS, dep_late: [ROW(300), ROW(300), ROW(300)] },
      LAX: { usual: [[0, 0, 0], [0, 0, 0], [0, 0, 0], ALL], runs: RUNS },
    },
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const { levels, usual, labels, pill } = await routeCells(page);
  // Part of each cancel number is the usual rate: marked, with no forecast level color.
  expect(levels.filter((level) => level !== null)).toEqual([]);
  expect(usual.filter((each) => !each)).toEqual([]);
  expect(labels.filter((label) => !label.endsWith('chance of a cancel, usual in part'))).toEqual(
    [],
  );
  expect(pill).toMatch(/^Usual in part\. Cancel chance \d+%\.$/u);
  const best = page.getByTestId('flights-best');
  expect(await factRows(best)).toEqual([
    'Usual rate | Part of both chances',
    'Left out | Weather and the FAA',
  ]);
});

test('says no past days on an old file, only its age', async ({ page }) => {
  await serveFlights(page, {
    generatedAt: new Date(Date.now() - 3 * 3_600_000),
    over: { JFK: { usual: CANCEL_USUAL, why: [[3], [3], []] } },
    records: { JFK: windRecord('JFK', 60, 12) },
  });
  await page.goto('/?mode=flights&airport=JFK');
  const answer = page.getByTestId('flights-answer');
  await expect(answer).toHaveClass(/is-old/, { timeout: 60_000 });
  await expect(answer).toContainText('Old: from 3 h ago');
  await expect(answer).not.toContainText(' since 2020');
  await expect(answer.locator('.fl-fact')).toHaveCount(0);
});

test('shows no track record count the live file contradicts, and a record that fits whole', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  const track = (late: number) => ({
    schema_version: 1,
    generated_at: '2026-11-22T14:11:13Z',
    test_first: '2025-10-01',
    test_last: '2026-09-30',
    usual_first: '2024-10-01',
    usual_last: '2025-09-30',
    tests: [
      {
        target: 1,
        lead: 1,
        skill: -0.01,
        skill_published: 0,
        skill_confirmed: 0,
        published: late === 0 ? 0 : 3,
        tested: 351,
        bins: [],
      },
    ],
    airports: ['DEN', 'LAX', 'MCI'].map((code) => ({ code, passed: [31, late, 31, 31, 31] })),
    months: [],
  });
  // The live file shows MCI's late chance from the forecast; this record passed it nowhere.
  await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000), track: track(0) });
  await page.goto('/?mode=flights&page=record');
  await expect(page.getByTestId('flights-track-not-shown')).toHaveText(
    'These scores are from Nov 22, 2026. They are not for the chances on the map now, so we do not show them.',
    { timeout: 60_000 },
  );
  await expect(page.getByText(/(Shown at|Passed the test at) \d+ of/u)).toHaveCount(0);
  await expect(page.getByTestId('flights-track')).toHaveCount(0);
  // Nor the same record's months.
  await expect(page.getByTestId('flights-track-months')).toHaveCount(0);

  await page.unrouteAll({ behavior: 'wait' });
  await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000), track: track(31) });
  await page.goto('/?mode=flights&page=record');
  await expect(page.getByTestId('flights-track')).toContainText(
    'Did not beat the usual rate. Passed the test at 3 of 351 airports.',
    { timeout: 60_000 },
  );
  await expect(page.getByTestId('flights-track-months')).toHaveCount(1);
  await expect(page.getByTestId('flights-track-not-shown')).toHaveCount(0);
});

test('draws Flights in the light theme in its own tokens', async ({ page, context }) => {
  await context.addInitScript(() => {
    localStorage.setItem('snowlight:theme', JSON.stringify({ id: 'daylight' }));
  });
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/?mode=flights&airport=MCI');
  const panel = page.locator('.mode-ui .detail');
  await expect(panel).toBeVisible({ timeout: 60_000 });
  const background = await panel.evaluate((element) => getComputedStyle(element).backgroundColor);
  // Daylight's surface is white; Midnight's is near black.
  expect(background).toBe('rgb(255, 255, 255)');
});

test('draws the switch as a sibling of the search under Snowball, its words whole in either face', async ({
  page,
  context,
}) => {
  await context.addInitScript(() => {
    localStorage.setItem('snowlight:theme', JSON.stringify({ id: 'snowball' }));
  });
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  /** The switch's look against the search box's beside it, and each mode's word in its button. */
  const look = (): Promise<{
    theme: string | null;
    switcher: { border: string; shadow: string; font: string };
    search: { border: string; shadow: string; font: string };
    words: { left: number; right: number; inLeft: number; inRight: number }[];
  }> =>
    page.evaluate(() => {
      const of = (box: string, words: string): { border: string; shadow: string; font: string } => {
        const element = document.querySelector(box);
        const text = document.querySelector(words);
        if (element === null || text === null) throw new Error(`no ${box}`);
        const style = getComputedStyle(element);
        return {
          border: style.borderTopWidth,
          shadow: style.boxShadow,
          font: getComputedStyle(text).fontFamily,
        };
      };
      return {
        theme: document.documentElement.getAttribute('data-theme'),
        switcher: of('.mode-switch', '.mode-switch .word'),
        search: of('header.bar > .search:not(.mode-own)', '.wordmark'),
        words: [...document.querySelectorAll('.mode-switch .mode')].map((button) => {
          const box = button.getBoundingClientRect();
          const word = button.querySelector('.word')?.getBoundingClientRect();
          const glyph = button.querySelector('svg')?.getBoundingClientRect();
          return {
            left: Math.min(glyph?.left ?? box.left, word?.left ?? box.left),
            right: word?.right ?? box.right,
            inLeft: box.left,
            inRight: box.right,
          };
        }),
      };
    });
  for (const address of ['/', '/?mode=flights']) {
    await page.goto(address);
    await expect(page.getByRole('radiogroup', { name: 'Show' })).toBeVisible({ timeout: 60_000 });
    await page.evaluate(() => document.fonts.ready);
    await expect.poll(async () => (await look()).theme, { timeout: 30_000 }).toBe('snowball');
    const seen = await look();
    // Snowball's ink outline and hard offset, and its face, as the search box and wordmark have.
    expect(seen.switcher.border).toBe(seen.search.border);
    expect(seen.switcher.shadow).toBe(seen.search.shadow);
    expect(seen.switcher.font).toBe(seen.search.font);
    expect(seen.switcher.font).toContain('Fredoka');
    // Every registered mode's word whole inside its own button (the switch's one width).
    for (const word of seen.words) {
      expect(word.left).toBeGreaterThanOrEqual(word.inLeft);
      expect(word.right).toBeLessThanOrEqual(word.inRight);
    }
  }
  // Flights' own menu, results and update line, each as Schools' own under Snowball (D1).
  const card = (selector: string, pseudo?: string): Promise<Record<string, string> | null> =>
    page.evaluate(
      ([box, after]) => {
        const element = document.querySelector(box);
        if (element === null) return null;
        const style = getComputedStyle(element, after);
        return {
          border: style.borderTopWidth,
          shadow: style.boxShadow,
          radius: style.borderTopLeftRadius,
          background: style.backgroundColor,
          content: style.content,
          position: style.position,
        };
      },
      [selector, pseudo] as const,
    );
  await page.goto('/');
  await expect(page.getByRole('radiogroup', { name: 'Show' })).toBeVisible({ timeout: 60_000 });
  await expect.poll(async () => (await look()).theme, { timeout: 30_000 }).toBe('snowball');
  await page.getByRole('button', { name: 'Menu' }).click();
  await expect(page.locator('.menu')).toBeVisible();
  const menu = await card('.menu');
  await page.keyboard.press('Escape');
  await page.goto('/?mode=flights');
  await expect(page.getByRole('button', { name: 'Flights menu' })).toBeVisible({
    timeout: 60_000,
  });
  await page.getByRole('button', { name: 'Flights menu' }).click();
  await expect(page.locator('.fl-menu')).toBeVisible();
  expect(await card('.fl-menu')).toEqual(menu);
  await page.keyboard.press('Escape');
  // Schools' results list needs a build with schools (app.spec): it is Snowball's card as the
  // menu is, with the 16px corners of its own sheet (SearchResults.svelte).
  await page.getByRole('combobox', { name: 'Search an airport, flight or route' }).fill('MCI');
  await expect(page.locator('.fl-results')).toBeVisible();
  expect(await card('.fl-results')).toEqual({ ...menu, radius: '16px' });
  // The update line on Snowball's sticker, as the key's beside it (and Schools' update time).
  await expect(page.locator('.fl-updated')).toBeVisible();
  const sticker = await card('.fl-updated', '::before');
  const key = await card('.flights-legend', '::before');
  expect(sticker?.content).toBe('""');
  expect({ ...sticker, radius: '' }).toEqual({ ...key, radius: '' });
  expect(sticker?.radius).toBe('14px');
});

test('fits each mode’s word whole in its button in the page’s own face, the widest', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/');
  await expect(page.getByRole('radiogroup', { name: 'Show' })).toBeVisible({ timeout: 60_000 });
  await page.evaluate(() => document.fonts.ready);
  const widths = await page.evaluate(() =>
    [...document.querySelectorAll('.mode-switch .mode')].map((button) => {
      const box = button.getBoundingClientRect();
      const word = button.querySelector('.word')?.getBoundingClientRect();
      const glyph = button.querySelector('svg')?.getBoundingClientRect();
      return {
        fits: (glyph?.left ?? box.left) >= box.left && (word?.right ?? box.right) <= box.right,
        font: getComputedStyle(button).fontFamily,
      };
    }),
  );
  for (const width of widths) {
    expect(width.font).toContain('Geist');
    expect(width.fits).toBe(true);
  }
});

test('says a failed live read inside the open panel, never that it is still reading', async ({
  page,
}) => {
  await page.route('**/data/flights/**', async (route) => {
    const name = new URL(route.request().url()).pathname;
    if (/latest\.json$|\/live\//.test(name)) await route.abort();
    else await route.fulfill({ status: 404, body: '' });
  });
  for (const address of [
    '/?mode=flights&airport=MCI',
    '/?mode=flights&route=MCI-LAX',
    '/?mode=flights&flight=WN1234-MCI',
  ]) {
    await page.goto(address);
    const panel = page.locator('.mode-ui .detail');
    await expect(panel).toContainText('We could not read the flight chances just now.', {
      timeout: 60_000,
    });
    await expect(panel).not.toContainText('Reading flight chances');
  }
});

test('fits a phone’s width with nothing running off the side', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(page.getByTestId('flights-grid')).toBeVisible({ timeout: 60_000 });
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    view: window.innerWidth,
    switcher: document.querySelector('.mode-switch')?.getBoundingClientRect().right ?? 0,
    menu: document.querySelector('.menu-button.mode-own')?.getBoundingClientRect().left ?? 0,
  }));
  expect(widths.page).toBeLessThanOrEqual(widths.view);
  expect(widths.switcher).toBeLessThanOrEqual(widths.menu);
});

test('leaves Schools as it was: with the switch hidden, the page of a build with no modes', async ({
  page,
}) => {
  // The page with no mode code at all, as before the switch: its chunk never loads.
  await page.route('**/assets/host-*.js', (route) => route.abort());
  await page.goto('/');
  await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(3000);
  expect(await page.locator('.mode-switch').count()).toBe(0);
  // The map's own frames are drawn by the GPU, whose last tile can land a frame apart between
  // two loads on a phone's screen: it is blanked in both, and every control over it compared.
  const map = page.locator('.stage > .map');
  const before = await page.screenshot({ animations: 'disabled', mask: [map] });
  await page.unrouteAll();

  await page.goto('/');
  const switcher = page.locator('.mode-switch');
  await expect(switcher).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(3000);
  // The switch taken out: anything else it or its code moved would differ.
  await switcher.evaluate((element) => {
    (element as HTMLElement).style.display = 'none';
  });
  const without = await page.screenshot({ animations: 'disabled', mask: [map] });
  if (!without.equals(before)) {
    await test.info().attach('before', { body: before, contentType: 'image/png' });
    await test.info().attach('without', { body: without, contentType: 'image/png' });
  }
  expect(without.equals(before)).toBe(true);
});

test('a Flights link never shows Schools first, and a round trip leaves Schools as a fresh load', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/?mode=flights', { waitUntil: 'domcontentloaded' });
  // Marked by the page's head before its first paint: Schools' key never shows.
  expect(await page.evaluate(() => document.documentElement.dataset.mode)).toBe('flights');
  await expect(page.locator('.stage > .legend')).toBeHidden();
  await expect(page.getByRole('radiogroup', { name: 'Show' })).toBeVisible({ timeout: 60_000 });
  await expect(
    page.locator('canvas[aria-label="Map of airports and their flight chances"]'),
  ).toHaveCount(1);
  await switchTo(page, 'Schools');
  await expectSchoolsWhole(page);
  await expect(page.locator('canvas[aria-label="Map of weather school closings"]')).toHaveCount(1);
  await page.waitForTimeout(1500);
  const map = page.locator('.stage > .map');
  const after = await page.screenshot({ animations: 'disabled', mask: [map] });
  // The map's labels as a fresh load has them: every layer's visibility and filter, and the
  // same place and state names drawn, none still held off by a tag that has gone.
  const labelsAfter = await labelState(page);
  await page.goto('/');
  await expectSchoolsWhole(page);
  await page.waitForTimeout(1500);
  const fresh = await page.screenshot({ animations: 'disabled', mask: [map] });
  expect(after.equals(fresh)).toBe(true);
  const labelsFresh = await labelState(page);
  expect(labelsAfter.layers).toEqual(labelsFresh.layers);
  expect(labelsAfter.names).toEqual(labelsFresh.names);
});

test('keeps every place name of the basemap, each giving way to the tags, never under one', async ({
  page,
}) => {
  // A storm over the Midwest: a crowd of tags over a crowd of names.
  await serveFlights(page, {
    generatedAt: new Date(Date.now() - 5 * 60_000),
    extra: [
      ['MDW', 'America/Chicago', 300],
      ['MKE', 'America/Chicago', 300],
      ['STL', 'America/Chicago', 300],
      ['DSM', 'America/Chicago', 300],
      ['OMA', 'America/Chicago', 300],
    ],
  });
  await page.goto('/?mode=flights');
  await expect(page.locator('.flights-legend')).toBeVisible({ timeout: 60_000 });
  const fresh = await page.evaluate(() => {
    const map = (window as unknown as { snowlightMap?: LabelMap }).snowlightMap;
    return (map?.getStyle().layers ?? [])
      .filter((layer) => layer.type === 'symbol' && /label-(city|town|village)/.test(layer.id))
      .map(
        (layer) =>
          `${layer.id} ${JSON.stringify(map?.getLayoutProperty(layer.id, 'visibility') ?? 'visible')}`,
      );
  });
  // No name layer hidden under Flights: the same basemap as Schools (D1).
  expect(fresh.length).toBeGreaterThan(3);
  expect(fresh.filter((each) => each.endsWith(' "none"'))).toEqual([]);
  const header = await page.locator('.stage > .bar').boundingBox();
  for (const [center, zoom] of [
    [[-90, 40.5], 3.9],
    [[-89, 41.5], 4.6],
    [[-88.5, 42], 5.5],
    [[-94.7, 39.3], 8],
  ] as const) {
    await tagsAt(page, [...center], zoom);
    const seen = await tagsAndNames(page);
    // Tags and names both on the map, and no tag over any label the map drew.
    expect(seen.boxes.length, `tags at ${String(zoom)}`).toBeGreaterThan(0);
    expect(seen.names, `names at ${String(zoom)}`).toBeGreaterThan(0);
    expect(seen.met, `labels under tags at ${String(zoom)}`).toEqual([]);
    // No two tags meet; each is whole inside the map, clear of the page's header.
    for (const [i, [, x0, y0, x1, y1]] of seen.boxes.entries()) {
      expect(x0).toBeGreaterThanOrEqual(0);
      expect(y0).toBeGreaterThanOrEqual(0);
      expect(x1).toBeLessThanOrEqual(seen.width);
      expect(y1).toBeLessThanOrEqual(seen.height);
      if (header !== null)
        expect(
          y0 >= header.y + header.height ||
            y1 <= header.y ||
            x0 >= header.x + header.width ||
            x1 <= header.x,
        ).toBe(true);
      for (const [, a0, b0, a1, b1] of seen.boxes.slice(i + 1))
        expect(x0 < a1 && a0 < x1 && y0 < b1 && b0 < y1).toBe(false);
    }
  }
});

test('with no WebGL, a Flights link and a kept Flights show Schools whole, never a bare page', async ({
  page,
}) => {
  // No WebGL at all (a GPU block list, Lockdown Mode): the map never comes up.
  await page.addInitScript(() => {
    type GetContext = (this: HTMLCanvasElement, kind: string, ...rest: unknown[]) => unknown;
    const get = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'getContext')
      ?.value as GetContext;
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
      configurable: true,
      writable: true,
      value: function (this: HTMLCanvasElement, kind: string, ...rest: unknown[]): unknown {
        return kind.includes('webgl') ? null : get.call(this, kind, ...rest);
      },
    });
  });
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  const schoolsShows = async (): Promise<void> => {
    await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
    await expect(
      page.getByRole('combobox', { name: 'Search a school, city, or ZIP' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Menu', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.dataset.mode)).toBeUndefined();
  };
  await page.goto('/?mode=flights');
  await schoolsShows();
  // The bare address on a device that kept Flights.
  await page.evaluate(() => {
    localStorage.setItem('snowlight:mode', 'flights');
  });
  await page.goto('/');
  await schoolsShows();
});

test('a Flights link draws no school layer in any frame, and Schools brings them back', async ({
  page,
}) => {
  // Every frame the map draws: the school layers on it, and those it draws (window.snowlightMap
  // is the map, set for a test browser).
  await page.addInitScript((ids: string[]) => {
    const drawn = new Set<string>();
    const present = new Set<string>();
    Object.assign(window, { schoolLayersDrawn: drawn, schoolLayersPresent: present });
    let held: unknown;
    Object.defineProperty(window, 'snowlightMap', {
      configurable: true,
      get: () => held,
      set: (map: {
        on: (event: string, listener: () => void) => void;
        getLayersOrder: () => string[];
        getLayer: (id: string) => { source?: string } | undefined;
        getLayoutProperty: (id: string, name: string) => unknown;
      }) => {
        held = map;
        map.on('render', () => {
          for (const id of map.getLayersOrder()) {
            if (!ids.includes(id) && map.getLayer(id)?.source !== 'schools') continue;
            present.add(id);
            if (map.getLayoutProperty(id, 'visibility') !== 'none') drawn.add(id);
          }
        });
      },
    });
  }, SCHOOL_LAYER_IDS);
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/?mode=flights');
  await expect(
    page.getByRole('list', { name: 'Chance of cancels and long delays today' }),
  ).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(1500);
  const read = (name: 'schoolLayersDrawn' | 'schoolLayersPresent'): Promise<string[]> =>
    page.evaluate(
      (key) => [...((window as unknown as Record<string, Set<string> | undefined>)[key] ?? [])],
      name,
    );
  // The school layers this build puts on the map, with or without data: none drawn in any frame
  // while Flights shows.
  const present = (await read('schoolLayersPresent')).filter((id) => !id.startsWith('later-'));
  test.info().annotations.push({ type: 'school layers', description: present.join(' ') });
  expect(await read('schoolLayersDrawn')).toEqual([]);
  // Schools again: every one of them drawn.
  await switchTo(page, 'Schools');
  await expect
    .poll(
      async () => {
        const drawn = await read('schoolLayersDrawn');
        return present.filter((id) => !drawn.includes(id));
      },
      { timeout: 30_000 },
    )
    .toEqual([]);
  expect(present.length).toBeGreaterThan(0);
});

/** The map's own calls a check needs (window.snowlightMap, set for a test browser). */
interface TestMap {
  getLayersOrder(): string[];
  getLayer(id: string): { source?: string } | undefined;
  getLayoutProperty(id: string, name: string): unknown;
  queryRenderedFeatures(options: { layers: string[] }): { properties: { code?: string } }[];
  jumpTo(options: { center: [number, number]; zoom: number }): void;
  once(event: string, listener: () => void): void;
  isStyleLoaded(): boolean;
  querySourceFeatures(source: string): unknown[];
  project(lonLat: [number, number]): { x: number; y: number };
  getCanvas(): HTMLCanvasElement;
}

/** The school layers (the glow among them) the map holds hidden: none, once Schools shows. */
async function hiddenSchoolLayers(page: Page): Promise<string[]> {
  return page.evaluate((ids: string[]) => {
    const map = (window as unknown as { snowlightMap?: TestMap }).snowlightMap;
    if (map === undefined) return ['no map'];
    return map
      .getLayersOrder()
      .filter((id) => ids.includes(id) || map.getLayer(id)?.source === 'schools')
      .filter((id) => !id.startsWith('later-'))
      .filter((id) => map.getLayoutProperty(id, 'visibility') === 'none');
  }, SCHOOL_LAYER_IDS);
}

/** Whether each of `codes` is on the map and clear of the open panel (beside it, or the sheet). */
async function inViewClearOfPanel(page: Page, codes: string[]): Promise<boolean> {
  // As public/flights/airports.json places them.
  const places: Record<string, [number, number]> = {
    MCI: [-94.7139, 39.3017],
    LAX: [-118.408, 33.9425],
  };
  const points = codes.map((code) => places[code]);
  return page.evaluate((lonLats) => {
    const map = (window as unknown as { snowlightMap?: TestMap }).snowlightMap;
    const panel = document.querySelector('.mode-ui .detail')?.getBoundingClientRect();
    if (map === undefined || panel === undefined) return false;
    const canvas = map.getCanvas().getBoundingClientRect();
    return lonLats.every((lonLat) => {
      if (lonLat === undefined) return false;
      const { x, y } = map.project(lonLat);
      const [px, py] = [canvas.left + x, canvas.top + y];
      const onScreen = px >= 0 && py >= 0 && px <= innerWidth && py <= innerHeight;
      const underPanel =
        px >= panel.left && px <= panel.right && py >= panel.top && py <= panel.bottom;
      return onScreen && !underPanel;
    });
  }, points);
}

/** A script the page loads whose body holds `marker`, aborted: a chunk that could not load. */
async function abortChunk(page: Page, marker: RegExp | string): Promise<void> {
  await page.route('**/assets/*.js', async (route) => {
    const url = route.request().url();
    if (typeof marker !== 'string') {
      if (marker.test(url)) await route.abort();
      else await route.fallback();
      return;
    }
    // A chunk still in flight when the test ends meets a closed page: nothing to answer.
    try {
      const response = await route.fetch();
      const body = await response.text();
      if (body.includes(marker)) await route.abort();
      else await route.fulfill({ response, body });
    } catch {
      // The page closed.
    }
  });
}

test('falls back to Schools whole, its glow and dots shown, when the modes code cannot load', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  // The modes' host chunk (modes/host.ts) never comes.
  await abortChunk(page, /\/host-[\w-]+\.js$/);
  for (const [address, kept] of [
    ['/', true],
    ['/?mode=flights', false],
  ] as const) {
    if (kept)
      await page.addInitScript(() => {
        localStorage.setItem('snowlight:mode', 'flights');
      });
    await page.goto(address);
    await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
    await expect(
      page.getByRole('combobox', { name: 'Search a school, city, or ZIP' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Menu', exact: true })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.mode))
      .toBe(undefined);
    // Never Schools' key over a map with its own marks hidden: every school layer and the glow
    // the map holds shows again.
    await expect.poll(() => hiddenSchoolLayers(page), { timeout: 30_000 }).toEqual([]);
    // The address says what the page shows.
    expect(new URL(page.url()).searchParams.get('mode')).toBeNull();
  }
});

test('falls back to Schools whole when the app code cannot load, on a device that kept Flights', async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem('snowlight:mode', 'flights');
  });
  // The app's boot chunk (app/boot.ts) never comes: no host, no mode.
  await abortChunk(page, /\/boot-[\w-]+\.js$/);
  await page.goto('/');
  await expect(page.getByRole('combobox', { name: 'Search a school, city, or ZIP' })).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByRole('button', { name: 'Menu', exact: true })).toBeVisible();
  await expect(page.locator('.stage > .legend')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.dataset.mode)).toBeUndefined();
  await expect.poll(() => hiddenSchoolLayers(page), { timeout: 30_000 }).toEqual([]);
});

test('a Flights code that cannot load leaves Schools and an address without the mode', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  // Flights' own chunk: the one that holds its map overlay's name.
  await abortChunk(page, 'flights-airport-tags');
  await page.goto('/?mode=flights&airport=MCI');
  await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.mode))
    .toBe(undefined);
  await expect.poll(() => new URL(page.url()).searchParams.get('mode')).toBeNull();
  await expect.poll(() => hiddenSchoolLayers(page), { timeout: 30_000 }).toEqual([]);
});

test('turns what it shows old by the clock when the live host cannot be read again', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciWhy: [[0], [], []],
  });
  await page.goto('/?mode=flights&airport=MCI');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-number')).toBeVisible({ timeout: 60_000 });
  // The host is gone (airport wifi): every read fails from here, and the clock runs on.
  await page.route('**/data/flights/**', (route) => route.abort());
  await page.clock.setFixedTime(new Date(NOW.getTime() + 61 * 60_000));
  // Within the page's 30 s clock: old, with its age, and no number said as current.
  await expect(answer).toHaveClass(/is-old/, { timeout: 45_000 });
  await expect(answer).toContainText('Old: from 1 h ago');
  await expect(answer.locator('.fl-hero-number')).toHaveCount(0);
  await expect(page.getByTestId('flights-blocks')).toHaveClass(/is-old/);
  await expect(page.getByTestId('flights-blocks').locator('[data-level]')).toHaveCount(0);
  await expect(page.getByTestId('flights-why-old')).toBeVisible();
  // The map's tags turn gray with it: no airport drawn at a level.
  await expect
    .poll(async () => {
      const tags = await shownTags(page);
      return tags.length > 0 && tags.every(([, look]) => look === 'none');
    })
    .toBe(true);
});

test('grays an old storm file on Best time to fly: no level, no safest time, gray rows', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 70 * 60_000),
    mciRows: [
      [360, 290, 610, 380, 160],
      [50, 40, 40, 40, 40],
      [40, 40, 40, 40, 40],
    ],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const best = page.getByTestId('flights-best');
  await expect(best).toContainText('Old: from 1 h ago', { timeout: 60_000 });
  await expect(best.locator('.fl-hero-number')).toHaveCount(0);
  const grid = page.getByTestId('flights-grid');
  await expect(grid).toHaveClass(/is-old/);
  await expect(grid.locator('[data-level]')).toHaveCount(0);
  await expect(grid.locator('[aria-pressed="true"]')).toHaveCount(0);
  const ink = await grid
    .locator('button.fl-cell')
    .first()
    .evaluate((node) => getComputedStyle(node).color);
  const gray = await page.evaluate(() => {
    const probe = document.createElement('span');
    probe.style.color = 'var(--text-3)';
    document.querySelector('.fl-grid')?.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  });
  expect(ink).toBe(gray);
  // A time picked by hand shows its flights with their numbers only: no level said as current.
  await grid.locator('button.fl-cell').first().click();
  const rows = page.locator('.fl-rows');
  await expect(rows).toContainText('Cancel chance');
  await expect(rows).not.toContainText('risk');
  await expect(rows.locator('[data-level]')).toHaveCount(0);
});

test('says a live FAA ground stop under a calm answer, at the airport, the flight and the route', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciCancel: 10,
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
    laxPrograms: [{ program: 1, minutes: 95, until: null, why: 1 }],
  });
  const stop = 'FAA at MCI | Ground stop now, not counted';
  const delay = 'FAA at LAX | Ground delay now, not counted';
  await page.goto('/?mode=flights&airport=MCI');
  const answer = page.getByTestId('flights-answer');
  await expect(answer.locator('.fl-hero-number')).toBeVisible({ timeout: 60_000 });
  // The airport's own panel names it already: the label is "FAA" alone.
  await expect.poll(() => factRows(answer)).toContain('FAA | Ground stop now, not counted');
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const flight = page.getByTestId('flights-answer');
  await expect.poll(() => factRows(flight), { timeout: 60_000 }).toContain(stop);
  const flightRows = await factRows(flight);
  expect(flightRows).toContain(delay);
  // Right under the headline, on the first screen of a phone's sheet: before the other rows.
  expect(flightRows.indexOf(stop)).toBeLessThan(flightRows.indexOf('Counts | Both airports'));
  // Whole, not a sliver under the sheet's edge: both ends' rows.
  await expect(flight.locator('.fl-fact', { hasText: 'FAA at MCI' })).toBeInViewport({ ratio: 1 });
  await expect(flight.locator('.fl-fact', { hasText: 'FAA at LAX' })).toBeInViewport({ ratio: 1 });
  // The flight's two ends in view, its arc drawn, clear of the panel.
  await expect.poll(() => inViewClearOfPanel(page, ['MCI', 'LAX']), { timeout: 30_000 }).toBe(true);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const map = (window as unknown as { snowlightMap?: TestMap }).snowlightMap;
        return map?.querySourceFeatures('flights-route').length ?? 0;
      }),
    )
    .toBeGreaterThan(0);
  await page.goto('/?mode=flights&airport=MCI');
  await expect(page.getByTestId('flights-answer')).toBeVisible({ timeout: 60_000 });
  // The picked airport sits clear of the panel, never under the phone's sheet.
  await expect.poll(() => inViewClearOfPanel(page, ['MCI']), { timeout: 30_000 }).toBe(true);
  await page.goto('/?mode=flights&route=MCI-LAX');
  // The live stop and delay hold today (no end given): no time today is named. Every time left
  // unheld shows the same 2%, so the line says so, leaving the held times out (LR-F15.1), says
  // why today is not named (LR-F15.3a), and gives the FAA's lines (LR-F14.3).
  const best = page.getByTestId('flights-best');
  await expect(best).toContainText(
    'Every time shows the same chance: 2%. It leaves out times with an FAA hold.',
    { timeout: 60_000 },
  );
  await expect(best).not.toContainText('safest');
  // Both live holds hold today; the FAA rows under it name each (TRAV-R12-S3, TRAV-R13-S3).
  const tieRows = await factRows(best);
  expect(tieRows).toContain('Today | Held by FAA holds');
  expect(tieRows).toContain(stop);
  expect(tieRows).toContain(delay);
  // The flights that usually fly then: their numbers only, never "Low risk" under a ground stop,
  // and today's with the FAA programs said by them.
  await page.getByTestId('flights-grid').locator('button.fl-cell').first().click();
  const rows = page.locator('.fl-rows');
  await expect(rows).toContainText('Cancel chance');
  await expect(rows).not.toContainText('risk');
  await expect(
    page.locator('.fl-block', { has: rows }).locator('.fl-fact', { hasText: 'FAA at MCI' }),
  ).toHaveText(/Ground stop now/);
});

/** Every number the route's grid shows, and the one pressed. */
async function gridNumbers(page: Page): Promise<{ all: string[]; pressed: string[] }> {
  const cells = page.getByTestId('flights-grid').locator('button.fl-cell');
  return {
    all: await cells.allInnerTexts(),
    pressed: await page
      .getByTestId('flights-grid')
      .locator('button.fl-cell[aria-pressed="true"]')
      .allInnerTexts(),
  };
}

const lowestOf = (texts: readonly string[]): number =>
  Math.min(...texts.map((text) => (text.startsWith('Under') ? 0 : Number.parseInt(text, 10))));

test('names the lowest time even a point under the rest, and says the same only for one number', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  const route = async (mciRows: (number | null)[][]): Promise<void> => {
    await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000), mciRows });
    await page.goto('/?mode=flights&route=MCI-LAX');
    await expect(page.getByTestId('flights-grid').locator('button.fl-cell').first()).toBeVisible({
      timeout: 60_000,
    });
  };
  const best = page.getByTestId('flights-best');
  // 2% at MCI today and Wednesday, 1% tomorrow: tomorrow's cells a point under (LR-F14.2).
  await route([
    [20, 20, 20, 20, 20],
    [10, 10, 10, 10, 10],
    [20, 20, 20, 20, 20],
  ]);
  await expect(best).toContainText('Chance of a cancel tomorrow');
  await expect(best).toContainText('It is the safest time to fly.');
  let shown = await gridNumbers(page);
  expect(new Set(shown.all).size).toBeGreaterThan(1);
  expect(shown.pressed).toHaveLength(1);
  expect(lowestOf(shown.pressed)).toBe(lowestOf(shown.all));
  // Never "same" while two cells show different numbers.
  await expect(best).not.toContainText('same');
  // Today and tomorrow equal and lowest: the earliest, today.
  await route([
    [10, 10, 10, 10, 10],
    [10, 10, 10, 10, 10],
    [20, 20, 20, 20, 20],
  ]);
  await expect(best).toContainText('Chance of a cancel today');
  await expect(best).not.toContainText('same');
  shown = await gridNumbers(page);
  expect(lowestOf(shown.pressed)).toBe(lowestOf(shown.all));
  // Every cell the same: the line says so, with the number.
  await route([
    [10, 10, 10, 10, 10],
    [10, 10, 10, 10, 10],
    [10, 10, 10, 10, 10],
  ]);
  shown = await gridNumbers(page);
  expect(new Set(shown.all).size).toBe(1);
  await expect(best).toContainText(`Every time shows the same chance: ${shown.all[0] ?? ''}.`);
  await expect(best).not.toContainText('safest');
  // Raw chances a point apart that all show 5% (47 and 52 per mille with LAX's 1%): one level,
  // one color, one rank, so the same line, never a "safest" pick among them (LR-F15.1).
  await route([
    [42, 42, 42, 42, 42],
    [37, 37, 37, 37, 37],
    [42, 42, 42, 42, 42],
  ]);
  shown = await gridNumbers(page);
  expect(new Set(shown.all)).toEqual(new Set(['5%']));
  await expect(best).toContainText('Every time shows the same chance: 5%.');
  await expect(best).not.toContainText('safest');
  const cells = page.getByTestId('flights-grid').locator('button.fl-cell');
  const levels = await cells.evaluateAll((all) =>
    all.map((cell) => cell.getAttribute('data-level')),
  );
  expect(new Set(levels)).toEqual(new Set(['delay']));
  // Each cell says its level in words too, never by its color alone (LR-F15.2).
  for (const name of await cells.evaluateAll((all) => all.map((c) => c.getAttribute('aria-label'))))
    expect(name).toMatch(/: 5% chance of a cancel, some risk$/);
});

test('never names a time a live ground stop holds as the safest, and points to the FAA when it holds them all', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  const rows: (number | null)[][] = [
    [20, 20, 20, 20, 20],
    [510, 510, 510, 510, 510],
    [610, 610, 610, 610, 610],
  ];
  const best = page.getByTestId('flights-best');
  const stop = { program: 0, minutes: null, until: null, why: 1 };
  // A live stop at MCI with no end: today's 2% is held, so tomorrow is named, at its own number.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: rows,
    programs: [stop],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best).toContainText('Chance of a cancel tomorrow', { timeout: 60_000 });
  await expect(best).not.toContainText('today');
  const heldRows = await factRows(best);
  expect(heldRows).toContain('FAA at MCI | Ground stop now, not counted');
  // Why today is not named (LR-F15.3a).
  expect(heldRows).toContain('Today | Held by the FAA ground stop at MCI');
  // The cell pressed is tomorrow's, never one inside the stop.
  const pressed = page.getByTestId('flights-grid').locator('button.fl-cell[aria-pressed="true"]');
  await expect(pressed).toHaveAttribute('aria-label', /Tomorrow/);
  // A stop set to end in four days holds every time: the line points to the FAA, with no number.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: rows,
    programs: [{ ...stop, until: '2026-01-09T00:00:00Z' }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best).toContainText(
    'The FAA has a ground stop at MCI now. Check back when it ends.',
    { timeout: 60_000 },
  );
  await expect(best.locator('.fl-hero-number')).toHaveCount(0);
  await expect(best).not.toContainText('safest');
  // An FAA read past its 30 minutes holds nothing, and says nothing as now.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programsAt: new Date(NOW.getTime() - 40 * 60_000),
    mciRows: rows,
    programs: [stop],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best).toContainText('Chance of a cancel today', { timeout: 60_000 });
  await expect(best).not.toContainText('Ground stop now');
  // Its age, as the airport panel gives it (LR-F15.3b).
  expect(await factRows(best)).toContain('FAA status | From 40 min ago');
  await expect(best).not.toContainText('Held by');
});

test('never says a stop past the end the FAA gave it as in place now, on any panel', async ({
  page,
}) => {
  // Read 5 minutes ago with a stop set to end 4 minutes ago (7:56 am in Kansas City): the read is
  // live, the stop's stated end has passed (TRAV-R10-B3).
  await page.clock.setFixedTime(NOW);
  const until = new Date(NOW.getTime() - 4 * 60_000).toISOString().replace(/\.\d+Z$/, 'Z');
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: [
      [20, 20, 20, 20, 20],
      [20, 20, 20, 20, 20],
      [20, 20, 20, 20, 20],
    ],
    programs: [{ program: 0, minutes: null, until, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const best = page.getByTestId('flights-best');
  await expect
    .poll(() => factRows(best), { timeout: 60_000 })
    .toContain('FAA at MCI | Ground stop was set to end at 7:56 am');
  await expect(best).not.toContainText(/ now\b/);
  await page.goto('/?mode=flights&airport=MCI');
  const panel = page.getByTestId('flights-answer');
  await expect(page.getByTestId('flights-faa')).toContainText(
    'Ground stop, set to end at 7:56 am',
    {
      timeout: 60_000,
    },
  );
  expect(await factRows(panel)).toContain('FAA | Ground stop was set to end at 7:56 am');
  await expect(panel).not.toContainText(/ now\b/);
});

test('says a hold past its stated end the ended way on every line, and presses the tie’s own time', async ({
  page,
}) => {
  // 5:30 pm in Kansas City: today's only time left is the evening, which began at 5 pm, inside a
  // stop set to end at 5:20 pm; the read is 5 minutes old, so live (TRAV-R11-B1, B2).
  const now = new Date('2026-01-05T23:30:00Z');
  await page.clock.setFixedTime(now);
  const rows: (number | null)[][] = [
    [10, 10, 10, 10, 10],
    [300, 300, 300, 300, 300],
    [300, 300, 300, 300, 300],
  ];
  const best = page.getByTestId('flights-best');
  const pressed = page.getByTestId('flights-grid').locator('button.fl-cell[aria-pressed="true"]');
  const until = '2026-01-05T23:20:00Z';
  await serveFlights(page, {
    generatedAt: new Date(now.getTime() - 5 * 60_000),
    mciRows: rows,
    programs: [{ program: 0, minutes: null, until, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect
    .poll(() => factRows(best), { timeout: 60_000 })
    .toContain('FAA at MCI | Ground stop was set to end at 5:20 pm');
  expect(await factRows(best)).toContain('Today | Not named until the next FAA update');
  const tie =
    /Every time shows the same chance: (\d+)%\. It leaves out times before the FAA hold was set to end\./;
  await expect(best).toContainText(tie);
  for (const said of ['Held by', 'with an FAA hold', 'in place', ' now'])
    await expect(best).not.toContainText(said);
  // The time pressed is the tie's own, the earliest no hold covers, at the headline's number.
  const number = tie.exec((await best.textContent()) ?? '')?.[1];
  await expect(pressed).toHaveAttribute('aria-label', /^Tomorrow, Morning: /);
  await expect(pressed).toHaveText(`${number ?? ''}%`);

  // LAX's ground delay past its end: its clock named, as every other time is Kansas City's (S4).
  await serveFlights(page, {
    generatedAt: new Date(now.getTime() - 5 * 60_000),
    mciRows: rows,
    laxPrograms: [{ program: 1, minutes: 45, until, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect
    .poll(() => factRows(best), { timeout: 60_000 })
    .toContain('FAA at LAX | Ground delay was set to end at 3:20 pm LAX time');
  expect(await factRows(best)).toContain('Today | Not named until the next FAA update');
  await expect(best).toContainText(/It leaves out times before the FAA hold was set to end\./);
  await expect(best).not.toContainText('Held by');
  await expect(pressed).toHaveAttribute('aria-label', /^Tomorrow, Morning: /);

  // Both past their ends over the same times: each is named on its own FAA row, and the held
  // cell's name stays short (TRAV-R12-S2, S3, TRAV-R13-S4).
  await serveFlights(page, {
    generatedAt: new Date(now.getTime() - 5 * 60_000),
    mciRows: rows,
    programs: [{ program: 0, minutes: null, until, why: 1 }],
    laxPrograms: [{ program: 1, minutes: 45, until, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best).toContainText(
    /Every time shows the same chance: \d+%\. It leaves out times before the FAA holds were set to end\./,
    { timeout: 60_000 },
  );
  const bothEnded = await factRows(best);
  expect(bothEnded).toContain('FAA at MCI | Ground stop was set to end at 5:20 pm');
  expect(bothEnded).toContain('FAA at LAX | Ground delay was set to end at 3:20 pm LAX time');
  expect(bothEnded).toContain('Today | Not named until the next FAA update');
  await expect(
    page.getByTestId('flights-grid').getByRole('button', { name: /^Today, Evening: / }),
  ).toHaveAccessibleName(
    /^Today, Evening: \d+% chance of a cancel, low risk, not named for FAA holds$/,
  );

  // A stop with no end, in force: today's 1% is held, and the time pressed is still the tie's own.
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: rows,
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const held = /Every time shows the same chance: (\d+)%\. It leaves out times with an FAA hold\./;
  await expect(best).toContainText(held, { timeout: 60_000 });
  expect(await factRows(best)).toContain('Today | Held by the FAA ground stop at MCI');
  await expect(pressed).toHaveAttribute('aria-label', /^Tomorrow, Morning: /);
  await expect(pressed).toHaveText(`${held.exec((await best.textContent()) ?? '')?.[1] ?? ''}%`);
  // A held cell says so by name, never as an open time lower than the headline (TRAV-R12-S2).
  const grid = page.getByTestId('flights-grid');
  await expect(grid.getByRole('button', { name: /^Today, Evening: / })).toHaveAccessibleName(
    /^Today, Evening: \d+% chance of a cancel, low risk, held by the FAA ground stop at MCI$/,
  );
  await expect(pressed).not.toHaveAttribute('aria-label', /held/);
});

test('says why a lower cancel chance is passed over, and a level from a long delay in words', async ({
  page,
}) => {
  // This evening shows the lowest cancel chance with a 30% chance of a long delay (Some risk);
  // every other time shows more, with no long delay (Low risk) (TRAV-R11-S1, S2, S3).
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: [
      [30, 30, 30, 20, 30],
      [30, 30, 30, 30, 30],
      [30, 30, 30, 30, 30],
    ],
    mciLate: [
      [0, 0, 0, 300, 0],
      [0, 0, 0, 0, 0],
      [0, 0, 0, 0, 0],
    ],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const best = page.getByTestId('flights-best');
  await expect(best).toContainText('Chance of a cancel today', { timeout: 60_000 });
  // The time passed over, as a row with its shown numbers (LR-F18.2); the grid shows its level.
  expect((await factRows(best)).filter((row) => row.startsWith('This evening | '))).toEqual([
    expect.stringMatching(/^This evening \| 3% cancel, \d+% delay$/),
  ]);
  const grid = page.getByTestId('flights-grid');
  await expect(grid.getByRole('button', { name: /^Today, Evening: / })).toHaveAccessibleName(
    'Today, Evening: 3% chance of a cancel, some risk of a long delay',
  );
  await expect(grid.getByRole('button', { name: /^Tomorrow, Morning: / })).toHaveAccessibleName(
    /^Tomorrow, Morning: \d+% chance of a cancel, low risk$/,
  );
  await expect(page.getByTestId('flights-late-note')).toHaveText(
    'A time can show more risk than its cancel chance when its chance of a long delay is high.',
  );
  // The airport's own blocks say the level their bars show, in words.
  await page.goto('/?mode=flights&airport=MCI');
  const evening = page.locator('ul.sr-only li', { hasText: /^Evening/ });
  await expect(evening).toHaveText(
    /^Evening, 5 to 9 pm\. Cancel: 2%, low risk\. 45\+ min late: 30%, some risk\.$/,
    { timeout: 60_000 },
  );
});

test('at the 25% late line, names the Low risk time and says the lower cancel chance passed over', async ({
  page,
}) => {
  // Today's evening shows 4% with 24% late (Low risk); tomorrow morning 3% with 25% late (Some
  // risk); every other time 9% (Some risk). With LAX's 1% cancel added and its 6% late under
  // MCI's, MCI's 30, 240 and 20, 250 per mille show as 4%, 24% and 3%, 25% (LR-F16.1, LR-F16.2,
  // TRAV-R12-B1).
  await page.clock.setFixedTime(NOW);
  const cancel = [
    [80, 80, 80, 30, 80],
    [80, 20, 80, 80, 80],
    [80, 80, 80, 80, 80],
  ];
  const late = (today: number, tomorrow: number): number[][] => [
    [60, 60, 60, today, 60],
    [60, tomorrow, 60, 60, 60],
    [60, 60, 60, 60, 60],
  ];
  const best = page.getByTestId('flights-best');
  const grid = page.getByTestId('flights-grid');
  const pressed = grid.locator('button.fl-cell[aria-pressed="true"]');
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: cancel,
    mciLate: late(240, 250),
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best.locator('.fl-hero-meaning')).toHaveText(
    '4% Chance of a cancel today, 5 to 9 pm. It is the safest time to fly.',
    { timeout: 60_000 },
  );
  const passedRows = await factRows(best);
  expect(passedRows).toContain('Delay of 45+ min | 24%');
  expect(passedRows).toContain('Tomorrow morning | 3% cancel, 25% delay');
  await expect(pressed).toHaveAccessibleName('Today, Evening: 4% chance of a cancel, low risk');
  await expect(grid.getByRole('button', { name: /^Tomorrow, Morning: / })).toHaveAccessibleName(
    'Tomorrow, Morning: 3% chance of a cancel, some risk of a long delay',
  );
  // The other way round: 3% with 24% late is the Low risk time, and nothing is passed over.
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: cancel,
    mciLate: late(250, 240),
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best.locator('.fl-hero-meaning')).toHaveText(
    '3% Chance of a cancel tomorrow, 9 am to noon. It is the safest time to fly.',
    { timeout: 60_000 },
  );
  const pickRows = await factRows(best);
  expect(pickRows).toContain('Delay of 45+ min | 24%');
  expect(pickRows.filter((row) => row.includes(' cancel, '))).toEqual([]);
});

test('opens a flight from a Best time row with the focus in it, and Escape gives the row back', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000) });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const grid = page.getByTestId('flights-grid');
  // A cell other than the one pressed at first, picked from the keyboard.
  const evening = grid.getByRole('button', { name: /^Tomorrow, Evening: / });
  await expect(evening).toBeVisible({ timeout: 60_000 });
  await evening.focus();
  await page.keyboard.press('Enter');
  await expect(evening).toHaveAttribute('aria-pressed', 'true');
  const row = page.locator('.mode-ui .detail .fl-row-button').first();
  const name = (await row.textContent()) ?? '';
  await row.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/flight=/);
  // The flight panel has the focus, as after a search pick, never the page itself (TRAV-R12-S1).
  await expect(page.locator('.mode-ui .detail')).toBeFocused();
  // Escape goes back to the route, its cell still picked, and gives the keyboard its row again.
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/route=MCI-LAX/);
  await expect(grid.getByRole('button', { name: /^Tomorrow, Evening: / })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  const back = page.locator('.mode-ui .detail .fl-row-button').first();
  await expect(back).toBeFocused();
  await expect(back).toHaveText(name);
  // Escape again closes the route, as any panel.
  await page.keyboard.press('Escape');
  await expect(page.locator('.mode-ui .detail')).toHaveCount(0);
});

test('comes back to the route a flight was tapped open from, by Close and by Back alike', async ({
  page,
  isMobile,
}) => {
  // A tap, as a phone screen reader taps too: the row gets the focus back, and the cell picked
  // stays picked by Close and by Back, with Close and Back one step (TRAV-R13-S1, S2).
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000) });
  // The route opened in the page, from the search, so every step below is one page's history.
  await page.goto('/?mode=flights');
  const field = page.getByRole('combobox', { name: 'Search an airport, flight or route' });
  await expect(field).toBeVisible({ timeout: 60_000 });
  await field.fill('MCI to LAX');
  await page.getByRole('option', { name: /MCI to LAX/ }).click();
  await expect(page).toHaveURL(/route=MCI-LAX/);
  const grid = page.getByTestId('flights-grid');
  const evening = grid.getByRole('button', { name: /^Tomorrow, Evening: / });
  await expect(evening).toBeVisible({ timeout: 60_000 });
  await evening.click();
  await expect(evening).toHaveAttribute('aria-pressed', 'true');
  const panel = page.locator('.mode-ui .detail');
  const rows = panel.locator('.fl-row-button');
  const name = (await rows.first().textContent()) ?? '';
  // A row under a phone's sheet edge is tapped as a screen reader taps it, without moving there.
  const openRow = async (): Promise<void> => {
    if (isMobile) await rows.first().dispatchEvent('click');
    else await rows.first().click();
    await expect(page).toHaveURL(/flight=/);
  };
  const pickedIsKept = async (): Promise<void> => {
    // A phone's sheet glides away before the panel closes.
    await expect(page).toHaveURL(/route=MCI-LAX/, { timeout: 30_000 });
    await expect(page).not.toHaveURL(/flight=/);
    await expect(grid.getByRole('button', { name: /^Tomorrow, Evening: / })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(rows.first()).toBeFocused();
    await expect(rows.first()).toHaveText(name);
  };
  // Close, tapped.
  await openRow();
  await panel.getByRole('button', { name: 'Close' }).click();
  await pickedIsKept();
  // Back after Close leaves the route, never opening the flight again.
  await page.goBack();
  await expect(page).not.toHaveURL(/route=|flight=/);
  await expect(panel).toHaveCount(0);
  // Forward to the route keeps its cell; Back from the flight, as a phone's back gesture.
  await page.goForward();
  await pickedIsKept();
  await openRow();
  await page.goBack();
  await pickedIsKept();
  // Forward to the flight again: its Close still comes back to the route's own entry.
  await page.goForward();
  await expect(page).toHaveURL(/flight=/);
  await panel.getByRole('button', { name: 'Close' }).click();
  await pickedIsKept();
  await page.goBack();
  await expect(page).not.toHaveURL(/route=|flight=/);
});

test('names every FAA hold at both ends, on the lines, the answer and a held cell', async ({
  page,
}) => {
  // A live stop and a live 60-minute delay at MCI, and a live delay at LAX (TRAV-R13-S3, S4).
  await page.clock.setFixedTime(NOW);
  const until = '2026-01-09T00:00:00Z';
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programs: [
      { program: 0, minutes: null, until: null, why: 1 },
      { program: 1, minutes: 60, until: null, why: 1 },
    ],
    laxPrograms: [{ program: 1, minutes: 45, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  const best = page.getByTestId('flights-best');
  await expect
    .poll(() => factRows(best), { timeout: 60_000 })
    .toEqual(
      expect.arrayContaining([
        'FAA at MCI | Ground stop now, not counted',
        'FAA at MCI | Ground delay now, not counted',
        'FAA at LAX | Ground delay now, not counted',
        'Today | Held by FAA holds',
      ]),
    );
  // A held cell's name is short: the lines name each hold.
  await expect(
    page.getByTestId('flights-grid').getByRole('button', { name: /^Today, Evening: / }),
  ).toHaveAccessibleName(/^Today, Evening: \d+% chance of a cancel, [a-z ]+, held by FAA holds$/);
  // Set to end in four days, they hold every time: the answer points to the FAA, and the rows
  // under it name each hold (TRAV-R13-S3).
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programs: [
      { program: 0, minutes: null, until, why: 1 },
      { program: 1, minutes: 60, until, why: 1 },
    ],
    laxPrograms: [{ program: 1, minutes: 45, until, why: 1 }],
  });
  await page.goto('/?mode=flights&route=MCI-LAX');
  await expect(best).toContainText('FAA holds cover every time now. Check back when they end.', {
    timeout: 60_000,
  });
  expect(await factRows(best)).toEqual([
    'FAA at MCI | Ground stop now',
    'FAA at MCI | Ground delay now',
    'FAA at LAX | Ground delay now',
  ]);
  await expect(best.locator('.fl-hero-number')).toHaveCount(0);
});

test('says a live FAA ground stop under a flight with no forecast for its day', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  const none = [null, null, null, null, null];
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    mciRows: [none, none, none],
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const flight = page.getByTestId('flights-answer');
  await expect(flight).toContainText('No forecast chance for this day yet.', { timeout: 60_000 });
  expect(await factRows(flight)).toContain('FAA at MCI | Ground stop now');
  // With no number above it, the fact alone: no "this chance" that points at nothing.
  await expect(flight).not.toContainText('this chance');
});

test('gives a keyboard its focus back when a panel closes, never to the page itself', async ({
  page,
}) => {
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  // A link's panel: nothing on the page opened it, so the focus goes to the search field.
  await page.goto('/?mode=flights&airport=MCI');
  const close = page.locator('.mode-ui .detail').getByRole('button', { name: 'Close' });
  await expect(close).toBeVisible({ timeout: 60_000 });
  await close.focus();
  await page.keyboard.press('Enter');
  const field = page.getByRole('combobox', { name: 'Search an airport, flight or route' });
  await expect(field).toBeFocused();
  // Opened from the search field: back to it.
  await field.fill('MCI');
  await expect(page.getByRole('option').first()).toBeVisible();
  await field.press('Enter');
  await expect(page.locator('.mode-ui .detail')).toBeFocused();
  await close.focus();
  await page.keyboard.press('Enter');
  await expect(field).toBeFocused();
  // Escape inside an open panel closes it, as in Schools, and the focus goes back the same way.
  await field.fill('MCI');
  await expect(page.getByRole('option').first()).toBeVisible();
  await field.press('Enter');
  await expect(page.locator('.mode-ui .detail')).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Escape');
  await expect(page.locator('.mode-ui .detail')).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get('airport')).toBeNull();
  await expect(field).toBeFocused();
  // The menu, opened from the keyboard, takes the focus, so its items come next in Tab order, and
  // Escape gives its button the focus back, as Schools' menu does (TRAV-R8-S1, S2).
  const menuButton = page.getByRole('button', { name: 'Flights menu' });
  await menuButton.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.fl-menu')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Past storms' })).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Escape');
  await expect(page.locator('.fl-menu')).toHaveCount(0);
  await expect(menuButton).toBeFocused();
  // A press anywhere else closes it, as in Schools.
  await page.keyboard.press('Enter');
  await expect(page.locator('.fl-menu')).toBeVisible();
  await field.focus();
  await expect(page.locator('.fl-menu')).toHaveCount(0);
});

test('titles an FAA read past its limit without "now", at the airport and the flight', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programsAt: new Date(NOW.getTime() - 45 * 60_000),
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&airport=MCI');
  const faa = page.getByTestId('flights-faa');
  await expect(faa).toContainText('FAA status from 45 min ago', { timeout: 60_000 });
  await expect(faa.locator('.fl-card-title')).toHaveText('FAA');
  await page.goto('/?mode=flights&flight=WN1234-MCI');
  const ends = page.getByTestId('flights-end');
  await expect(ends.first()).toContainText('FAA status from 45 min ago', { timeout: 60_000 });
  for (const title of await ends.locator('.fl-card-title').allInnerTexts())
    expect(title).not.toContain('now');
  // Nor any line under it on a later day: the flight's tomorrow, and the airport's Tomorrow tab.
  const noNow = (texts: string[]): void => {
    for (const text of texts) expect(text).not.toMatch(/\bnow\b/);
  };
  await page.goto('/?mode=flights&flight=WN1234-MCI&day=1');
  await expect(ends.first()).toContainText('last status from the FAA', { timeout: 60_000 });
  noNow(await ends.allInnerTexts());
  await page.goto('/?mode=flights&airport=MCI');
  await page.getByRole('group', { name: 'Day' }).getByRole('button', { name: 'Tomorrow' }).click();
  await expect(faa).toContainText('last status from the FAA', { timeout: 30_000 });
  noNow(await faa.allInnerTexts());
  // A fresh read keeps "now".
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  await serveFlights(page, {
    generatedAt: new Date(NOW.getTime() - 5 * 60_000),
    programs: [{ program: 0, minutes: null, until: null, why: 1 }],
  });
  await page.goto('/?mode=flights&airport=MCI');
  await expect(page.getByTestId('flights-faa').locator('.fl-card-title')).toHaveText('FAA now', {
    timeout: 60_000,
  });
});

test('offers the regional flight for a ticket number it runs under, never says it does not fly', async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await serveFlights(page, { generatedAt: new Date(NOW.getTime() - 5 * 60_000), regional: true });
  await page.goto('/?mode=flights&flight=DL5489-MCI');
  const offer = page.getByTestId('flights-regional');
  await expect(offer).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.mode-ui .detail')).toContainText(
    'SkyWest flies OO 5489 from MCI to LAX at 8:20 pm for bigger airlines. Is this your flight?',
  );
  await expect(page.locator('.mode-ui .detail')).not.toContainText('does not usually fly');
  await offer.click();
  await expect(page).toHaveURL(/flight=OO5489-MCI/);
  await expect(page.getByTestId('flights-card')).toContainText('8:20 pm');
  // A number with no flight at all: said as not found, with where regional ones are listed.
  await page.goto('/?mode=flights&flight=DL4321-MCI');
  await expect(page.locator('.mode-ui .detail')).toContainText(
    'We could not find DL 4321 from MCI in the flights that usually fly.',
    { timeout: 60_000 },
  );
});

/** Jumps the map to `center` at `zoom`, and gives the tags its overlay shows once it rests. */
async function tagsAt(page: Page, center: [number, number], zoom: number): Promise<string[]> {
  await page.evaluate(
    async ([at, z]) => {
      const map = (window as unknown as { snowlightMap?: TestMap }).snowlightMap;
      if (map === undefined) return;
      map.jumpTo({ center: at, zoom: z });
      await new Promise<void>((resolve) => {
        map.once('idle', () => {
          resolve();
        });
      });
    },
    [center, zoom] as const,
  );
  return (await shownTags(page)).map(([code]) => code);
}

test('draws airport code tags: the one in trouble wins a crowded spot', async ({ page }) => {
  // Midway at high risk beside a calm O'Hare: Midway's tag shows, O'Hare's gives way.
  await serveFlights(page, {
    generatedAt: new Date(Date.now() - 5 * 60_000),
    extra: [['MDW', 'America/Chicago', 300]],
  });
  await page.goto('/?mode=flights');
  await expect(
    page.getByRole('list', { name: 'Chance of cancels and long delays today' }),
  ).toBeVisible({ timeout: 60_000 });
  await expect.poll(() => tagsAt(page, [-88, 41.9], 4), { timeout: 30_000 }).toContain('MDW');
  expect(await tagsAt(page, [-88, 41.9], 4)).not.toContain('ORD');
  // Zooming in brings in smaller airports, still with no overlaps.
  const national = await tagsAt(page, [-96, 38], 3);
  const closer = await tagsAt(page, [-88, 41.9], 7);
  expect(national.length).toBeGreaterThan(5);
  expect(closer).toContain('ORD');
  expect(new Set(closer).size).toBe(closer.length);
  // No two tags drawn meet: their boxes as drawn.
  const { boxes } = await tagsAndNames(page);
  expect(boxes.length).toBe(closer.length);
  for (const [i, [, x0, y0, x1, y1]] of boxes.entries())
    for (const [, a0, b0, a1, b1] of boxes.slice(i + 1))
      expect(x0 < a1 && a0 < x1 && y0 < b1 && b0 < y1).toBe(false);
});

test('draws airport code tags: of two at the same risk, the busier one', async ({ page }) => {
  // On a fresh file, read in a page of its own, so the tags are at their level, not gray: the
  // busier one then wins for its departures, not for an old file's gray.
  await serveFlights(page, {
    generatedAt: new Date(Date.now() - 5 * 60_000),
    extra: [
      ['MDW', 'America/Chicago', 300],
      ['ORD', 'America/Chicago', 300],
    ],
  });
  await page.goto('/?mode=flights');
  const legend = page.locator('.flights-legend');
  await expect(legend).toBeVisible({ timeout: 60_000 });
  await expect(legend).not.toHaveClass(/is-old/);
  await expect(page.locator('.fl-updated')).not.toHaveClass(/is-old/);
  const looks = async (): Promise<Record<string, string>> =>
    Object.fromEntries(await shownTags(page));
  await tagsAt(page, [-88, 41.9], 7);
  await expect.poll(looks, { timeout: 30_000 }).toMatchObject({ ORD: 'cancel', MDW: 'cancel' });
  for (const zoom of [2, 3, 4]) {
    await expect.poll(() => tagsAt(page, [-88, 41.9], zoom), { timeout: 30_000 }).toContain('ORD');
    expect((await looks()).ORD).toBe('cancel');
    // Midway, as much at risk but less busy, gives the crowded spot up.
    expect(await tagsAt(page, [-88, 41.9], zoom)).not.toContain('MDW');
  }
});

test('builds no WebGL program at start that Schools does not', async ({ page }) => {
  // Each program a mode's layers add costs a phone's graphics a long frame at start (LR-F13):
  // Flights draws its airports on a 2D canvas over the map instead.
  await page.addInitScript(() => {
    const counted = window as unknown as { programs: number };
    counted.programs = 0;
    for (const gl of [WebGLRenderingContext.prototype, WebGL2RenderingContext.prototype]) {
      const original = Object.getOwnPropertyDescriptor(gl, 'linkProgram')?.value as (
        this: WebGLRenderingContext,
        program: WebGLProgram,
      ) => void;
      gl.linkProgram = function (this: WebGLRenderingContext, program: WebGLProgram) {
        counted.programs += 1;
        original.call(this, program);
      };
    }
  });
  const programs = (): Promise<number> =>
    page.evaluate(() => (window as unknown as { programs: number }).programs);
  await serveFlights(page, { generatedAt: new Date(Date.now() - 5 * 60_000) });
  await page.goto('/');
  await expect(page.locator('.stage > .legend')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(3000);
  const schools = await programs();
  expect(schools).toBeGreaterThan(0);
  await page.goto('/?mode=flights');
  await expect(page.locator('.flights-legend')).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(async () => (await shownTags(page)).length, { timeout: 30_000 })
    .toBeGreaterThan(0);
  await page.waitForTimeout(3000);
  expect(await programs()).toBeLessThanOrEqual(schools);
});

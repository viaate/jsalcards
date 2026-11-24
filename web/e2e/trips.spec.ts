/**
 * Flights trips (flights spec FL-3) on the accounts build: Save with the one-tap ticket type, the
 * leg pick, Backup plans with the money words, My trips, Connect Google dormant until it is set
 * up, calendar flights confirmed before they are saved, and the demo-only Gmail button. The API
 * and the flights files are made up (e2e/trips-stub.ts): nothing leaves the machine.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';

import { connectedAs, tripsCopy } from '../src/copy-trips';
import { ACCOUNTS_URL } from './accounts-server';
import { TRIPS_NOW, TripsApi, serveTripFlights, type StubTrip } from './trips-stub';

test.use({ baseURL: ACCOUNTS_URL, serviceWorkers: 'block' });
test.describe.configure({ timeout: 120_000 });

async function open(page: Page, api: TripsApi, search: string): Promise<void> {
  await page.clock.setFixedTime(TRIPS_NOW);
  await serveTripFlights(page);
  await api.attach(page);
  await page.goto(`/${search}`);
}

/**
 * Presses a control in the open panel from the keyboard: on a phone the sheet grows as what has
 * the focus comes into view, as for a screen reader, where a tap could land under its edge.
 */
async function press(page: Page, control: Locator): Promise<void> {
  await control.focus();
  await page.keyboard.press('Enter');
}

function saved(overrides: Partial<StubTrip> = {}): StubTrip {
  return {
    id: '1'.padStart(32, '0'),
    carrier: 'WN',
    number: 1234,
    from: 'MCI',
    to: 'LAX',
    day: '2026-01-05',
    leaves: 600,
    lands: 720,
    ticket: 'unsure',
    ticket_asked: true,
    need_by: null,
    source: 'typed',
    ...overrides,
  };
}

test('saves a flight, asks the ticket type once, and shows Backup plans with the money words', async ({
  page,
}) => {
  const api = new TripsApi();
  await open(page, api, '?mode=flights&flight=WN1234-MCI');
  const panel = page.locator('.mode-ui .detail');
  await press(page, panel.getByTestId('trip-save'));
  const tap = panel.getByTestId('ticket-tap');
  await expect(tap).toBeVisible();
  await expect(tap.getByRole('button')).toHaveText([
    tripsCopy.ticket.basic,
    tripsCopy.ticket.regular,
    tripsCopy.ticket.premium,
    tripsCopy.ticket.unsure,
    tripsCopy.ticket.skip,
  ]);
  expect(api.sent.find((s) => s.method === 'POST')?.body).toEqual({
    carrier: 'WN',
    number: 1234,
    from: 'MCI',
    to: 'LAX',
    day: '2026-01-05',
    leaves: 600,
    lands: 720,
  });
  await press(page, tap.getByRole('button', { name: tripsCopy.ticket.basic }));
  await expect(tap).toHaveCount(0);
  expect(api.sent.find((s) => s.method === 'PATCH')?.body).toEqual({ ticket: 'basic' });
  const row = panel.getByTestId('ticket-row');
  await expect(row.getByRole('button', { name: tripsCopy.ticket.basic })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // Backup plans: the trip is at high risk (snow this morning), so the safer ways lead.
  const plans = panel.getByTestId('backup-plans');
  await expect(plans.getByTestId('backup-plan').first()).toBeVisible();
  const first = await plans.getByTestId('backup-plan').first().innerText();
  expect(first).toMatch(/WN 1500 at 3:00 pm|AA 88 at 6:00 pm|WN 77 at 6:30 pm/);
  // A one stop with a legal layover is a plan; one with 20 minutes at DEN is not.
  await expect(plans).toContainText('WN 300 at 1:00 pm and WN 400 through DEN');
  expect(await plans.innerText()).not.toMatch(/WN 300 at 1:00 pm and WN 401/);
  await expect(panel.getByTestId('backup-money')).toContainText(tripsCopy.backup.money);
  await expect(panel.getByTestId('backup-advice')).toContainText(tripsCopy.advice.basic);
  await expect(panel.getByTestId('backup-advice')).toContainText(tripsCopy.backup.mustGo);
  expect(await plans.innerText()).not.toMatch(/\$\d|seats? left|on sale/i);
});

test('asks which leg when the number makes more than one stop that day', async ({ page }) => {
  const api = new TripsApi();
  await open(page, api, '?mode=flights&flight=UA420-MCI');
  const panel = page.locator('.mode-ui .detail');
  await press(page, panel.getByTestId('trip-save'));
  const legs = panel.getByTestId('trip-legs');
  await expect(legs.getByRole('button')).toHaveCount(2);
  await press(page, legs.getByRole('button', { name: /MCI to LAX/ }));
  await expect(panel.getByTestId('ticket-tap')).toBeVisible();
  expect((api.sent.find((s) => s.method === 'POST')?.body as { to: string }).to).toBe('LAX');
  // Skip is Not sure, said once.
  await press(
    page,
    panel.getByTestId('ticket-tap').getByRole('button', { name: tripsCopy.ticket.skip }),
  );
  // The tap's PATCH goes out after the press: waited for, never read the same moment.
  await expect
    .poll(() => api.sent.find((s) => s.method === 'PATCH')?.body)
    .toEqual({ ticket_asked: true });
});

test('My trips shows the next trip big, later ones below, past ones folded, and opens one', async ({
  page,
}) => {
  const api = new TripsApi();
  api.trips = [
    saved(),
    saved({ id: '2'.padStart(32, '0'), number: 1500, day: '2026-01-07', leaves: 900, lands: 1020 }),
    saved({ id: '3'.padStart(32, '0'), number: 9, day: '2026-01-02' }),
  ];
  await open(page, api, '?mode=flights&page=trips');
  const panel = page.locator('.mode-ui .detail');
  await expect(panel.getByTestId('trip-next')).toContainText('MCI');
  await expect(panel.getByTestId('trip-next')).toContainText('High risk');
  await expect(panel.getByTestId('trips-later')).toContainText('WN 1500');
  await expect(panel.getByTestId('trips-past')).toHaveCount(0);
  await press(page, panel.getByRole('button', { name: tripsCopy.past }));
  await expect(panel.getByTestId('trips-past')).toContainText('WN 9');
  await press(page, panel.getByTestId('trip-next').getByRole('button'));
  await expect(page).toHaveURL(/page=trips&trip=0{31}1/);
  await expect(page.locator('.mode-ui .detail').getByTestId('trip-saved')).toBeVisible();
});

test('signed out, My trips says what trips are for and opens the sign-in', async ({ page }) => {
  const api = new TripsApi();
  api.signedIn = false;
  await open(page, api, '?mode=flights&page=trips');
  const panel = page.locator('.mode-ui .detail');
  await expect(panel).toContainText(tripsCopy.signedOut);
  await press(page, panel.getByTestId('trips-sign-in'));
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('Google stays dormant until it is set up: no Google option, no Google script, no errors', async ({
  page,
}) => {
  const api = new TripsApi();
  api.trips = [saved()];
  const errors: string[] = [];
  const google: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (/google\.com|googleapis\.com/.test(request.url())) google.push(request.url());
  });
  await open(page, api, '?mode=flights&page=trips');
  const panel = page.locator('.mode-ui .detail');
  await expect(panel.getByTestId('trip-next')).toBeVisible();
  await expect(panel.getByTestId('trips-google')).toHaveCount(0);
  await expect(panel.getByText(tripsCopy.google.connect)).toHaveCount(0);
  await expect(panel.getByText(tripsCopy.google.gmail)).toHaveCount(0);
  expect(google).toEqual([]);
  expect(errors).toEqual([]);
});

test('set up: calendar flights are shown to confirm, and only the trip is saved', async ({
  page,
}) => {
  const api = new TripsApi();
  api.google = {
    configured: true,
    client_id: 'made-up.apps.googleusercontent.com',
    gmail_demo: false,
    gmail_client_id: null,
  };
  api.connected = true;
  api.events = [
    {
      summary: 'Flight to Los Angeles (WN 1500)',
      location: 'Kansas City MCI',
      description: '',
      start: '2026-01-06T15:00:00-06:00',
      start_day: null,
      zone: 'America/Chicago',
      end: null,
    },
  ];
  const chunks: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('gmail-read-')) chunks.push(request.url());
  });
  await open(page, api, '?mode=flights&page=trips');
  const section = page.locator('.mode-ui .detail').getByTestId('trips-google');
  await expect(section).toContainText('pat@example.com');
  // The day it was connected (a Google client in Testing mode ends its link after 7 days).
  await expect(section).toContainText('Connected as pat@example.com since Fri, Jan 2');
  // The Gmail demo is off: no button, and its code never loads.
  await expect(section.getByTestId('gmail-find')).toHaveCount(0);
  await press(page, section.getByRole('button', { name: tripsCopy.google.calendar }));
  const found = section.getByTestId('google-found');
  await expect(found).toContainText('WN 1500 on Tue, Jan 6');
  expect(api.sent.filter((s) => s.method === 'POST' && s.path === '/v1/me/trips')).toEqual([]);
  await press(page, found.getByRole('button', { name: tripsCopy.ticket.regular }));
  await press(page, found.getByTestId('found-add'));
  await expect(found).toContainText(tripsCopy.added);
  expect(api.sent.find((s) => s.method === 'POST' && s.path === '/v1/me/trips')?.body).toEqual({
    carrier: 'WN',
    number: 1500,
    from: 'MCI',
    to: 'LAX',
    day: '2026-01-06',
    leaves: 900,
    lands: 1020,
    ticket: 'regular',
    source: 'calendar',
  });
  expect(chunks).toEqual([]);
});

test('the Gmail button shows only with the demo flag, with what it reads and sends', async ({
  page,
}) => {
  const api = new TripsApi();
  api.google = {
    configured: true,
    client_id: 'made-up.apps.googleusercontent.com',
    gmail_demo: true,
    gmail_client_id: 'made-up-demo.apps.googleusercontent.com',
  };
  await open(page, api, '?mode=flights&page=trips');
  const section = page.locator('.mode-ui .detail').getByTestId('trips-google');
  await expect(section.getByTestId('google-connect')).toBeVisible();
  await expect(section.getByTestId('gmail-find')).toBeVisible();
  await expect(section).toContainText(tripsCopy.google.gmailHint);
});

test('the Gmail demo after Connect Google uses its own client, revokes it, and leaves the link alive', async ({
  page,
}) => {
  const api = new TripsApi();
  api.google = {
    configured: true,
    client_id: 'made-up.apps.googleusercontent.com',
    gmail_demo: true,
    gmail_client_id: 'made-up-demo.apps.googleusercontent.com',
  };
  api.connected = true;
  // A made-up Google Identity Services: it records what the read asks for and every revoke.
  await page.addInitScript(() => {
    const seen = { asked: [] as unknown[], revoked: [] as string[] };
    (window as unknown as { gisSeen: typeof seen }).gisSeen = seen;
    (window as unknown as { google: unknown }).google = {
      accounts: {
        oauth2: {
          initTokenClient(config: {
            client_id: string;
            scope: string;
            include_granted_scopes?: boolean;
            callback: (answer: { access_token: string }) => void;
          }) {
            seen.asked.push({
              client: config.client_id,
              scope: config.scope,
              granted: config.include_granted_scopes,
            });
            return {
              requestAccessToken: () => {
                config.callback({ access_token: 'made-up-demo-token' });
              },
            };
          },
          revoke(token: string) {
            seen.revoked.push(token);
          },
        },
      },
    };
  });
  await page.route('https://gmail.googleapis.com/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"messages":[]}' }),
  );
  await open(page, api, '?mode=flights&page=trips');
  const section = page.locator('.mode-ui .detail').getByTestId('trips-google');
  await expect(section).toContainText('pat@example.com');
  await press(page, section.getByTestId('gmail-find'));
  await expect(section).toContainText(tripsCopy.google.gmailNone);
  const seen = await page.evaluate(
    () => (window as unknown as { gisSeen: { asked: unknown[]; revoked: string[] } }).gisSeen,
  );
  // Its own client (its own Google project): its revoke can never end the Connect Google link,
  // so it always revokes, and no Gmail read grant is left standing.
  expect(seen.asked).toEqual([
    {
      client: 'made-up-demo.apps.googleusercontent.com',
      scope: 'https://www.googleapis.com/auth/gmail.readonly',
      granted: false,
    },
  ]);
  expect(seen.revoked).toEqual(['made-up-demo-token']);
  // The link still works: the calendar import goes through, and it still reads as connected.
  await expect(section).toContainText('pat@example.com');
  await press(page, section.getByRole('button', { name: tripsCopy.google.calendar }));
  await expect(section).toContainText(tripsCopy.google.noneFound);
  expect(api.sent.filter((s) => s.path === '/v1/me/google/calendar')).toHaveLength(1);
});

test('a reconnect Google refuses reads the state again: never connected on a link that ended', async ({
  page,
}) => {
  // SAFE-R2-B1: the refused finish also ended the old link of that Google account (one grant).
  const api = new TripsApi();
  api.google = {
    configured: true,
    client_id: 'made-up.apps.googleusercontent.com',
    gmail_demo: false,
    gmail_client_id: null,
  };
  api.connected = true;
  api.finishRefused = true;
  await page.addInitScript(() => {
    window.sessionStorage.setItem(
      'snowlight:google-return',
      JSON.stringify({ code: 'made-up-code', state: 'made-up-state' }),
    );
  });
  await open(page, api, '?mode=flights&page=trips');
  const section = page.locator('.mode-ui .detail').getByTestId('trips-google');
  await expect(section).toContainText(tripsCopy.google.failed);
  await expect(section.getByTestId('google-connect')).toBeVisible();
  await expect(section).not.toContainText('pat@example.com');
  expect(api.sent.filter((s) => s.path === '/v1/me/google/finish')).toHaveLength(1);
});

test('a return from Google is finished before the page reads the Google state, and shows the new link', async ({
  page,
}) => {
  // SAFE-R4-B1: a read of the old link sent beside the finish could end the new one, or show
  // the old link's day as current. The finish's answer is the state.
  const api = new TripsApi();
  api.google = {
    configured: true,
    client_id: 'made-up.apps.googleusercontent.com',
    gmail_demo: false,
    gmail_client_id: null,
  };
  api.connected = true;
  await page.addInitScript(() => {
    window.sessionStorage.setItem(
      'snowlight:google-return',
      JSON.stringify({ code: 'made-up-code', state: 'made-up-state' }),
    );
  });
  await open(page, api, '?mode=flights&page=trips');
  const section = page.locator('.mode-ui .detail').getByTestId('trips-google');
  await expect(section).toContainText(connectedAs('pat@example.com', '2026-01-09'));
  await expect(section).not.toContainText(tripsCopy.google.failed);
  const google = api.sent.filter((s) => s.path.startsWith('/v1/me/google'));
  expect(google.map((s) => s.path)).toEqual(['/v1/me/google/finish']);
});

test('Settings for a Flights-only account says whether trip alerts reach this device', async ({
  page,
}) => {
  const api = new TripsApi();
  await open(page, api, '?mode=flights');
  await page.getByRole('button', { name: 'Account menu for Pat' }).click();
  await page.getByRole('menuitem', { name: 'Settings' }).click();
  const sheet = page.getByRole('dialog', { name: 'Settings' });
  const group = sheet.getByTestId('notify-flights');
  await expect(group).toBeVisible();
  // No saved school: the note is about school alerts only, never a condition for trip alerts.
  await expect(sheet).toContainText(tripsCopy.notify.noSchools);
  await expect(sheet).not.toContainText('Save a school first');
  // The browser blocks notifications (headless Chromium's default): said, with no button.
  await expect(group.getByTestId('flights-device')).toContainText(tripsCopy.notify.deviceBlocked);
  await expect(group).toContainText(tripsCopy.notify.blockedHint);
  await expect(group.getByTestId('flights-turn-on')).toHaveCount(0);
  // Allowed but not on: trip alerts will not come here, and the group offers to turn it on.
  // Headless Chromium answers "denied" without asking; a browser never asked says "default".
  await page.evaluate(() => {
    Object.defineProperty(Notification, 'permission', {
      configurable: true,
      get: () => 'default',
    });
  });
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0);
  await page.getByRole('button', { name: 'Account menu for Pat' }).click();
  await page.getByRole('menuitem', { name: 'Settings' }).click();
  await expect(group.getByTestId('flights-device')).toContainText(tripsCopy.notify.deviceOff);
  await expect(group).toContainText(tripsCopy.notify.offHint);
  await expect(group.getByTestId('flights-turn-on')).toBeVisible();
  // What the threshold is, in words, and when the evening check comes.
  await expect(group.getByText(tripsCopy.notify.threshold, { exact: true })).toBeVisible();
  await expect(group.getByRole('radiogroup', { name: tripsCopy.notify.threshold })).toBeVisible();
  await expect(group).toContainText(tripsCopy.notify.thresholdHint);
  await expect(group).toContainText(tripsCopy.notify.nightTime);
  await expect(group.getByTestId('flights-night-time')).toHaveValue('20:00');
  await group.getByTestId('flights-night-time').selectOption('19:00');
  await expect
    .poll(() => api.sent.find((s) => s.method === 'PATCH' && s.path === '/v1/me/flights/notify'))
    .toMatchObject({ body: { night_time: '19:00' } });
});

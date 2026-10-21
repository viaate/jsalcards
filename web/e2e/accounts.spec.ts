import { webcrypto } from 'node:crypto';
import { cpSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test, type Page, type Route } from '@playwright/test';
import { build, preview, type PreviewServer } from 'vite';

import { format } from '../src/copy-format';

import { ACCOUNTS_API, ACCOUNTS_URL } from './accounts-server';

// The accounts build (VITE_API_ROOT set to a made-up root), with no service worker in the way of
// the routes that answer for the API.
test.use({ baseURL: ACCOUNTS_URL, serviceWorkers: 'block' });

/** The key the browser derives (src/account/key.ts), worked out here the same way. */
async function deriveKey(login: string, password: string): Promise<string> {
  const enc = new TextEncoder();
  const salt = await webcrypto.subtle.digest(
    'SHA-256',
    enc.encode(`snowlight-v1|${login.trim().toLowerCase()}`),
  );
  const base = await webcrypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await webcrypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 600_000 },
    base,
    256,
  );
  return Buffer.from(bits).toString('base64url');
}

interface StubUser {
  id: string;
  name: string;
  email: string | null;
  role: 'user' | 'admin';
  key: string;
  schools: { id: string; name: string }[];
}

/** An accounts API in memory, answering the page's requests to the made-up root. */
class StubApi {
  up = true;
  users: StubUser[] = [];
  sessions = new Map<string, string>();
  overrides: Record<string, unknown>[] = [];
  /** Every request body the page sent, to check no password ever left it. */
  bodies: string[] = [];

  async attach(page: Page): Promise<void> {
    await page.route(`${ACCOUNTS_API}/**`, (route) => this.answer(route));
    await page.route('https://api.github.com/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: route.request().url().includes('/issues') ? '[]' : '{"workflow_runs":[]}',
        headers: { 'access-control-allow-origin': '*' },
      }),
    );
  }

  private publicUser(user: StubUser): Record<string, unknown> {
    return {
      id: user.id,
      name: user.name,
      email: user.email,
      role: user.role,
      schools: user.schools,
      created_at: '2026-10-20T00:00:00.000Z',
    };
  }

  private signIn(user: StubUser): Record<string, unknown> {
    const token = user.id.padEnd(43, 'x');
    this.sessions.set(token, user.id);
    return { token, user: this.publicUser(user) };
  }

  private async answer(route: Route): Promise<void> {
    const request = route.request();
    const cors = {
      // The accounts build's origin, or the build with a directory's (below).
      'access-control-allow-origin': request.headers().origin ?? ACCOUNTS_URL,
      'access-control-allow-headers': 'Authorization, Content-Type',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    };
    const reply = (status: number, body: unknown): Promise<void> =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
        headers: cors,
      });
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
    if (!this.up) return reply(503, { error: 'server' });
    const path = new URL(request.url()).pathname;
    const raw = request.postData() ?? '';
    if (raw !== '') this.bodies.push(raw);
    const body = (raw === '' ? {} : JSON.parse(raw)) as Record<string, unknown>;
    const token = (request.headers().authorization ?? '').replace(/^Bearer /, '');
    const me = this.users.find((u) => u.id === this.sessions.get(token)) ?? null;

    if (path === '/v1/health') return reply(200, { ok: true, api: 1 });
    if (path === '/v1/signup') {
      const user: StubUser = {
        id: `u${String(this.users.length + 1)}`,
        name: String(body.name),
        email: String(body.email),
        role: 'user',
        key: String(body.key),
        schools: [],
      };
      this.users.push(user);
      return reply(201, this.signIn(user));
    }
    if (path === '/v1/login') {
      const user = this.users.find((u) => (u.email ?? u.name.toLowerCase()) === body.login);
      if (user === undefined || user.key !== body.key) return reply(401, { error: 'bad_login' });
      return reply(200, this.signIn(user));
    }
    if (me === null) return reply(401, { error: 'signed_out' });
    if (path === '/v1/logout') {
      this.sessions.delete(token);
      return reply(200, { ok: true });
    }
    if (path === '/v1/me') return reply(200, { user: this.publicUser(me) });
    if (path === '/v1/me/schools') {
      me.schools = body.schools as StubUser['schools'];
      return reply(200, { user: this.publicUser(me) });
    }
    if (me.role !== 'admin') return reply(403, { error: 'forbidden' });
    if (path === '/v1/admin/summary')
      return reply(200, {
        accounts: { total: 2, new_day: 1, new_week: 2, disabled: 0, active_week: 2 },
        overrides_active: this.overrides.length,
      });
    if (path === '/v1/admin/users')
      return reply(200, { users: [], total: 0, page: 1, page_size: 50 });
    if (path === '/v1/admin/audit') return reply(200, { entries: [], page: 1, page_size: 50 });
    if (path === '/v1/admin/overrides' && request.method() === 'PUT') {
      const key = `${String(body.scope)}:${String(body.id)}`;
      this.overrides = [
        ...this.overrides.filter((o) => o.key !== key),
        { ...body, key, set_at: '2026-10-20T18:00:00Z', set_by: 'Olivia', active: true },
      ];
      return reply(200, { override: this.overrides.at(-1) });
    }
    if (path === '/v1/admin/overrides') return reply(200, { overrides: this.overrides });
    return reply(404, { error: 'not_found' });
  }
}

const PASSWORD = 'quiet snowy morning';

async function openPage(page: Page, api: StubApi, path = '/'): Promise<void> {
  await api.attach(page);
  await page.goto(path);
}

test.describe('accounts', () => {
  test('show nothing while the API does not answer', async ({ page }) => {
    const api = new StubApi();
    api.up = false;
    const health = page.waitForRequest(`${ACCOUNTS_API}/v1/health`);
    await openPage(page, api);
    await health;
    await page.waitForTimeout(500);
    await expect(page.locator('.account')).toHaveCount(0);
    // The strip keeps the control's room all the same, so nothing moves if it comes.
    expect(await page.evaluate(() => document.documentElement.hasAttribute('data-accounts'))).toBe(
      true,
    );
  });

  test('sign up, see the name, open the menu and log out', async ({ page }) => {
    const api = new StubApi();
    await openPage(page, api);
    const control = page.getByRole('button', { name: 'Sign up or log in' });
    await expect(control).toBeVisible();
    if (test.info().project.name === 'desktop') {
      // On the strip's one line, after the menu's button, with its words whole.
      const [button, menuButton] = await Promise.all([
        control.boundingBox(),
        page.locator('.menu-button').boundingBox(),
      ]);
      expect(button && menuButton).toBeTruthy();
      if (button && menuButton) {
        expect(
          Math.abs(button.y + button.height / 2 - (menuButton.y + menuButton.height / 2)),
        ).toBeLessThan(2);
        expect(button.x).toBeGreaterThan(menuButton.x + menuButton.width);
      }
      expect(
        await control.locator('.label').evaluate((el) => el.scrollWidth <= el.clientWidth),
      ).toBe(true);
    }
    await control.click();
    await page.getByRole('button', { name: 'New here? Sign up' }).click();
    const sheet = page.getByRole('dialog');
    await sheet.getByLabel('Name').fill('Sam Rivera');
    await sheet.getByLabel('Email').fill('sam@example.com');
    await sheet.getByLabel('Password', { exact: true }).fill(PASSWORD);
    await sheet.getByLabel('I am 13 or older').check();
    await sheet.getByRole('button', { name: 'Create account' }).click();

    const named = page.getByRole('button', { name: 'Account menu for Sam Rivera' });
    await expect(named).toBeVisible({ timeout: 20_000 });
    if (test.info().project.name === 'desktop') await expect(named).toContainText('Sam');
    // The password itself never left the page: only the key derived from it.
    expect(api.bodies.some((body) => body.includes(PASSWORD))).toBe(false);
    expect(api.users[0]?.key).toBe(await deriveKey('sam@example.com', PASSWORD));

    await named.click();
    const menu = page.getByRole('menu');
    await expect(menu.getByRole('menuitem')).toHaveText(['My schools', 'Settings', 'Log out']);
    await menu.getByRole('menuitem', { name: 'Log out' }).click();
    await expect(page.getByRole('button', { name: 'Sign up or log in' })).toBeVisible();
  });

  test('log in, stay logged in on reload, and see no admin view as a user', async ({ page }) => {
    const api = new StubApi();
    api.users.push({
      id: 'u9',
      name: 'Jo',
      email: 'jo@example.com',
      role: 'user',
      key: await deriveKey('jo@example.com', PASSWORD),
      schools: [],
    });
    await openPage(page, api, '/?admin');
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    const sheet = page.getByRole('dialog');
    await sheet.getByLabel('Email').fill('Jo@Example.com');
    await sheet.getByLabel('Password').fill('wrong password here');
    await sheet.getByRole('button', { name: 'Log in' }).click();
    await expect(sheet.getByRole('alert')).toHaveText(
      'That email and password don’t match an account.',
      { timeout: 20_000 },
    );
    await sheet.getByLabel('Password').fill(PASSWORD);
    await sheet.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('button', { name: 'Account menu for Jo' })).toBeVisible({
      timeout: 20_000,
    });
    await page.reload();
    await expect(page.getByRole('button', { name: 'Account menu for Jo' })).toBeVisible();
    await page.waitForTimeout(500);
    await expect(page.getByRole('heading', { name: 'Admin' })).toHaveCount(0);
  });

  test('fit the strip at 320 px without overlap', async ({ browser }) => {
    test.skip(test.info().project.name !== 'phone', 'a phone’s width');
    const context = await browser.newContext({
      viewport: { width: 320, height: 640 },
      hasTouch: true,
      isMobile: true,
      serviceWorkers: 'block',
    });
    const page = await context.newPage();
    const api = new StubApi();
    await api.attach(page);
    await page.goto(ACCOUNTS_URL);
    const account = page.getByRole('button', { name: 'Sign up or log in' });
    await expect(account).toBeVisible();
    const boxes = await page.evaluate(() =>
      ['.wordmark', '.account-button', '.menu-button'].map((selector) => {
        const box = document.querySelector(selector)?.getBoundingClientRect();
        return box === undefined ? null : { left: box.left, right: box.right };
      }),
    );
    const [wordmark, control, menu] = boxes;
    expect(wordmark && control && menu).toBeTruthy();
    if (wordmark && control && menu) {
      expect(wordmark.right).toBeLessThanOrEqual(control.left);
      expect(control.right).toBeLessThanOrEqual(menu.left);
      expect(menu.right).toBeLessThanOrEqual(320);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      320,
    );
    await context.close();
  });
});

const WEB = fileURLToPath(new URL('..', import.meta.url));

/**
 * SYNTHETIC: one made-up Oregon district (4100001) of two schools in Pacific time, as its
 * predictions file says (the state's easternmost zone, Mountain, is not the school's).
 */
const STAMP = { generated_on: '2026-10-14', schools: 2, districts: 1 };
const PACIFIC = 'America/Los_Angeles';

function directoryFiles(data: string): void {
  mkdirSync(path.join(data, 'schools'), { recursive: true });
  writeFileSync(
    path.join(data, 'schools/meta.json'),
    JSON.stringify({
      schema_version: 1,
      generated_on: STAMP.generated_on,
      count: STAMP.schools,
      ids: ['410000100001', '410000100002'],
      names: ['Made-up Elementary', 'Made-up High'],
      districts: { ids: ['4100001'], names: ['Made-up School District'] },
      school_years: { public: '2024-2025', private: '2023-2024' },
    }),
  );
  // The points file (src/data/directory.ts): a header, then 13 bytes a school.
  const points = Buffer.alloc(16 + 13 * STAMP.schools);
  points.write('SLPT', 0, 'latin1');
  points.writeUInt16LE(1, 4);
  points.writeUInt16LE(13, 6);
  points.writeUInt32LE(STAMP.schools, 8);
  points.writeUInt32LE(STAMP.districts, 12);
  for (let i = 0; i < STAMP.schools; i++) {
    points.writeInt32LE(-122_680_000 + i * 10_000, 16 + 13 * i);
    points.writeInt32LE(45_520_000, 16 + 13 * i + 4);
    points.writeUInt32LE(0, 16 + 13 * i + 8);
  }
  writeFileSync(path.join(data, 'schools/points.bin'), points);
  mkdirSync(path.join(data, 'predictions'), { recursive: true });
  writeFileSync(
    path.join(data, 'predictions/latest.json'),
    JSON.stringify({
      schema_version: 1,
      generated_at: '2026-10-21T06:00:00Z',
      directory: STAMP,
      days: ['2026-10-20', '2026-10-21'],
      districts: [
        {
          district: 0,
          time_zone: PACIFIC,
          neighbors: [],
          days: [{ state: 'no_threat' }, { state: 'no_threat' }],
        },
      ],
    }),
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

test.describe('the admin view with a directory', () => {
  test.describe.configure({ mode: 'default' });
  let root = '';
  let server: PreviewServer | undefined;
  let site = '';

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    if (test.info().project.name !== 'desktop') return;
    root = mkdtempSync(path.join(tmpdir(), 'snowlight-admin-e2e-'));
    const publicDir = path.join(root, 'public');
    cpSync(path.join(WEB, 'public'), publicDir, {
      recursive: true,
      filter: (source) => !path.relative(path.join(WEB, 'public'), source).startsWith('data'),
    });
    directoryFiles(path.join(publicDir, 'data'));
    const before = process.env.VITE_API_ROOT;
    process.env.VITE_API_ROOT = ACCOUNTS_API;
    try {
      await build({
        root: WEB,
        publicDir,
        cacheDir: path.join(root, 'vite-cache'),
        logLevel: 'warn',
        build: { outDir: path.join(root, 'site'), emptyOutDir: true },
      });
    } finally {
      if (before === undefined) delete process.env.VITE_API_ROOT;
      else process.env.VITE_API_ROOT = before;
    }
    const port = await freePort();
    server = await preview({
      root: WEB,
      logLevel: 'warn',
      build: { outDir: path.join(root, 'site') },
      preview: { host: '127.0.0.1', port, strictPort: true },
    });
    site = `http://127.0.0.1:${String(port)}/`;
  });

  test.afterAll(async () => {
    await server?.close();
    if (root !== '') rmSync(root, { recursive: true, force: true });
  });

  /** Logs the admin in on the site at `at` (its clock runs on from there) and opens Statuses. */
  async function openStatuses(page: Page, api: StubApi, at: string): Promise<void> {
    test.skip(test.info().project.name !== 'desktop', 'one screen is enough for the admin form');
    api.users.push({
      id: 'a1',
      name: 'Olivia',
      email: null,
      role: 'admin',
      key: await deriveKey('olivia', PASSWORD),
      schools: [],
    });
    await page.clock.install({ time: new Date(at) });
    await api.attach(page);
    await page.goto(`${site}?admin`);
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    const sheet = page.getByRole('dialog');
    await sheet.getByLabel('Email').fill('Olivia');
    await sheet.getByLabel('Password').fill(PASSWORD);
    await sheet.getByRole('button', { name: 'Log in' }).click();
    await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible({ timeout: 20_000 });
    await page.getByRole('tab', { name: 'Statuses' }).click();
    await page.getByRole('searchbox', { name: 'Find a school or district' }).fill('4100001');
    await page.getByRole('button', { name: 'District 4100001' }).click();
  }

  test('the admin sets a manual status in the school’s own zone, with its dates', async ({
    page,
  }) => {
    const api = new StubApi();
    // 10:00 AM Tuesday in Portland: 1:00 PM in Denver, the state's easternmost zone.
    await openStatuses(page, api, '2026-10-20T17:00:00Z');
    await page.getByLabel('Delayed').check();
    await page.getByLabel('Minutes late').fill('90');
    await page.getByLabel('Note, only admins see it').fill('Called the office');
    // Before 3 PM in the school's zone: today, with its date.
    const tue = format.day('2026-10-20');
    const wed = format.day('2026-10-21');
    await expect(page.getByLabel(`Today (${tue})`, { exact: true })).toBeChecked();
    await expect(page.getByLabel(`Tomorrow (${wed})`, { exact: true })).not.toBeChecked();
    await page.getByLabel(`Today and tomorrow (${tue} and ${wed})`, { exact: true }).check();
    await page.getByRole('button', { name: 'Set status' }).click();

    await expect(page.getByRole('cell', { name: 'Delayed 90 minutes' })).toBeVisible();
    await expect(page.getByText('Waiting to publish')).toHaveCount(2);
    expect(api.overrides[0]).toMatchObject({
      scope: 'district',
      id: '4100001',
      status: 'delayed',
      minutes: 90,
      note: 'Called the office',
      days: ['2026-10-20', '2026-10-21'],
      time_zone: PACIFIC,
    });
    expect(api.overrides[0]).not.toHaveProperty('expires_at');

    await page.getByRole('button', { name: 'Back to the map' }).click();
    await expect(page.getByRole('heading', { name: 'Admin' })).toHaveCount(0);
    expect(new URL(page.url()).searchParams.has('admin')).toBe(false);
  });

  test('a day picked before the school’s midnight is the date it showed when saved after it', async ({
    page,
  }) => {
    const api = new StubApi();
    // 11:58 PM Tuesday in Portland (already Wednesday in Denver and New York).
    await openStatuses(page, api, '2026-10-21T06:58:00Z');
    const [tue, wed, thu] = ['2026-10-20', '2026-10-21', '2026-10-22'].map((day) =>
      format.day(day),
    );
    // After 3 PM: tomorrow, Wednesday.
    const tomorrow = page.getByLabel(`Tomorrow (${wed ?? ''})`, { exact: true });
    await expect(tomorrow).toBeChecked();
    await expect(page.getByLabel(`Today (${tue ?? ''})`, { exact: true })).toBeVisible();
    // The school's midnight passes with the form open: Wednesday is now its today, still
    // picked, and Thursday is never sent in its place.
    await page.clock.fastForward('03:00');
    const today = page.getByLabel(`Today (${wed ?? ''})`, { exact: true });
    await expect(today).toBeChecked();
    await expect(page.getByLabel(`Tomorrow (${thu ?? ''})`, { exact: true })).not.toBeChecked();
    await page.getByRole('button', { name: 'Set status' }).click();
    await expect(page.getByRole('cell', { name: 'Closed' })).toBeVisible();
    expect(api.overrides[0]).toMatchObject({ days: ['2026-10-21'], time_zone: PACIFIC });

    // Today (Wednesday) picked, and the next midnight passes before the save: nothing is
    // picked in its place, and the admin is asked to pick again.
    await today.check();
    await page.clock.fastForward('24:00:00');
    await expect(page.getByRole('alert')).toHaveText(
      'The school’s date has changed. Pick its days again.',
    );
    await expect(page.getByRole('button', { name: 'Set status' })).toBeDisabled();
    await expect(page.getByLabel(`Today (${thu ?? ''})`, { exact: true })).not.toBeChecked();
    expect(api.overrides).toHaveLength(1);
  });
});

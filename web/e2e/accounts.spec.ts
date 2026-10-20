import { webcrypto } from 'node:crypto';

import { expect, test, type Page, type Route } from '@playwright/test';

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
      'access-control-allow-origin': ACCOUNTS_URL,
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

  test('the admin sets a manual status from the admin view', async ({ page }) => {
    test.skip(test.info().project.name !== 'desktop', 'one screen is enough for the admin form');
    const api = new StubApi();
    api.users.push({
      id: 'a1',
      name: 'Olivia',
      email: null,
      role: 'admin',
      key: await deriveKey('olivia', PASSWORD),
      schools: [],
    });
    await openPage(page, api, '/?admin');
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    const sheet = page.getByRole('dialog');
    await sheet.getByLabel('Email').fill('Olivia');
    await sheet.getByLabel('Password').fill(PASSWORD);
    await sheet.getByRole('button', { name: 'Log in' }).click();

    await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('All accounts')).toBeVisible();
    await page.getByRole('tab', { name: 'Statuses' }).click();
    await page.getByRole('searchbox', { name: 'Find a school or district' }).fill('3904378');
    await page.getByRole('button', { name: 'District 3904378' }).click();
    await page.getByLabel('Delayed').check();
    await page.getByLabel('Minutes late').fill('90');
    await page.getByLabel('Note, only admins see it').fill('Called the office');
    await page.getByRole('button', { name: 'Set status' }).click();

    await expect(page.getByRole('cell', { name: 'Delayed 90 minutes' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Waiting to publish' })).toBeVisible();
    const sent = api.overrides[0];
    expect(sent).toMatchObject({
      scope: 'district',
      id: '3904378',
      status: 'delayed',
      minutes: 90,
      note: 'Called the office',
    });
    // Ohio's day ends at 23:59 Eastern: 03:59 or 04:59 UTC.
    expect(String(sent?.expires_at)).toMatch(/T0[34]:59:00\.000Z$/);

    await page.getByRole('button', { name: 'Back to the map' }).click();
    await expect(page.getByRole('heading', { name: 'Admin' })).toHaveCount(0);
    expect(new URL(page.url()).searchParams.has('admin')).toBe(false);
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

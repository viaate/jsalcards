import { createHash, webcrypto } from 'node:crypto';
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

/** A v1 key's salt (and the admin's): SHA-256 of "snowlight-v1|" + the login, base64url. */
const loginSalt = (login: string): string =>
  createHash('sha256').update(`snowlight-v1|${login.trim().toLowerCase()}`).digest('base64url');

/** The key the browser derives (src/account/key.ts) for a salt, worked out here the same way. */
async function deriveKey(salt: string, password: string): Promise<string> {
  const base = await webcrypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveBits'],
  );
  const bits = await webcrypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: Buffer.from(salt, 'base64url'), iterations: 600_000 },
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
  /** The email key, salted with the email's v1 salt (emailSalt records it; null for a v1 account). */
  key: string;
  emailSalt: string | null;
  /** The username key and its salt; null for a v1 account. */
  nameKey: string | null;
  nameSalt: string | null;
  username: string | null;
  join: number | null;
  renamed: boolean;
  schools: { id: string; name: string }[];
}

/** A user of this version: the email key with the email's v1 salt, the username key with its own. */
async function stubUser(
  over: Partial<StubUser> & Pick<StubUser, 'id' | 'name' | 'email'>,
): Promise<StubUser> {
  const emailSalt = loginSalt(over.email ?? '');
  const nameSalt = Buffer.alloc(16, 2).toString('base64url');
  return {
    role: 'user',
    key: await deriveKey(emailSalt, PASSWORD),
    emailSalt,
    nameKey: await deriveKey(nameSalt, PASSWORD),
    nameSalt,
    username: null,
    join: 2,
    renamed: false,
    schools: [],
    ...over,
  };
}

/** An accounts API in memory, answering the page's requests to the made-up root. */
class StubApi {
  up = true;
  users: StubUser[] = [];
  sessions = new Map<string, string>();
  overrides: Record<string, unknown>[] = [];
  terms: { term: string; kind: string; added_at: string }[] = [];
  /** Every request body the page sent, to check no password ever left it. */
  bodies: string[] = [];
  /** Every admin rename's body. */
  renames: Record<string, unknown>[] = [];
  /** The account's notification settings (src/account/notify.ts), as the Worker keeps them. */
  notify: Record<string, unknown> = {
    status: true,
    chance: true,
    threshold: 50,
    night_before: false,
    night_time: '20:00',
    quiet_from: '22:00',
    quiet_to: '05:00',
  };

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
      username: user.username,
      join_number: user.join,
      username_required: user.role === 'user' && (user.username === null || user.renamed),
      renamed: user.role === 'user' && user.renamed,
      needs_rekey: user.role === 'user' && (user.emailSalt === null || user.nameSalt === null),
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
    const url = new URL(request.url());
    const path = url.pathname;
    const raw = request.postData() ?? '';
    if (raw !== '') this.bodies.push(raw);
    const body = (raw === '' ? {} : JSON.parse(raw)) as Record<string, unknown>;
    const token = (request.headers().authorization ?? '').replace(/^Bearer /, '');
    const me = this.users.find((u) => u.id === this.sessions.get(token)) ?? null;

    if (path === '/v1/health') return reply(200, { ok: true, api: 1 });
    if (path === '/v1/signup') {
      if (this.users.some((u) => u.username === body.username))
        return reply(409, { error: 'username_taken' });
      // As the Worker: the email key's salt must be the email's v1 salt.
      const emailSalt = loginSalt(String(body.email));
      if (body.email_salt !== emailSalt) return reply(400, { error: 'bad_key' });
      const user: StubUser = {
        id: `u${String(this.users.length + 1)}`,
        name: String(body.name),
        email: String(body.email),
        role: 'user',
        key: String(body.key),
        emailSalt,
        nameKey: String(body.name_key),
        nameSalt: String(body.name_salt),
        username: String(body.username),
        join: this.users.length + 2,
        renamed: false,
        schools: [],
      };
      this.users.push(user);
      return reply(201, this.signIn(user));
    }
    if (path === '/v1/login/salt') {
      const login = String(body.login);
      // Every email gets its v1 salt, as the Worker answers.
      if (login === 'olivia' || login.includes('@')) return reply(200, { salt: loginSalt(login) });
      const byName = this.users.find((u) => u.username === login);
      return reply(200, { salt: byName?.nameSalt ?? Buffer.alloc(16, 9).toString('base64url') });
    }
    if (path === '/v1/login') {
      const login = String(body.login);
      const user =
        login === 'olivia'
          ? this.users.find((u) => u.role === 'admin')
          : login.includes('@')
            ? this.users.find((u) => u.email === login)
            : this.users.find((u) => u.username === login);
      const key = login.includes('@') || login === 'olivia' ? user?.key : user?.nameKey;
      if (user === undefined || key !== body.key) return reply(401, { error: 'bad_login' });
      return reply(200, this.signIn(user));
    }
    if (path === '/v1/usernames/check') {
      const name = url.searchParams.get('name') ?? '';
      return reply(
        200,
        this.users.some((u) => u.username === name)
          ? { ok: false, problem: 'username_taken' }
          : { ok: true, username: name },
      );
    }
    if (me === null) return reply(401, { error: 'signed_out' });
    if (path === '/v1/logout') {
      this.sessions.delete(token);
      return reply(200, { ok: true });
    }
    if (path === '/v1/me' && request.method() === 'PATCH') {
      // Fresh keys: a v1 account's first login, or a new password or email.
      const emailSalt = loginSalt(typeof body.email === 'string' ? body.email : (me.email ?? ''));
      if (body.email_salt !== emailSalt) return reply(400, { error: 'bad_key' });
      me.key = String(body.new_key);
      me.emailSalt = emailSalt;
      me.nameKey = String(body.name_key);
      me.nameSalt = String(body.name_salt);
      return reply(200, this.signIn(me));
    }
    if (path === '/v1/me') return reply(200, { user: this.publicUser(me) });
    if (path === '/v1/me/notify') {
      this.notify = { ...this.notify, ...(request.method() === 'PATCH' ? body : {}) };
      return reply(200, { settings: this.notify, devices: 0 });
    }
    if (path === '/v1/me/username') {
      if (this.users.some((u) => u.username === body.username && u !== me))
        return reply(409, { error: 'username_taken' });
      me.username = String(body.username);
      me.renamed = false;
      return reply(200, { user: this.publicUser(me) });
    }
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
      return reply(200, {
        users: this.users.map((u) => ({
          id: u.id,
          name: u.name,
          email: u.email,
          username: u.username,
          join_number: u.join,
          rename_required: u.renamed,
          role: u.role,
          created_at: '2026-10-20T00:00:00Z',
          last_login_at: null,
          schools: u.schools.length,
          disabled: false,
        })),
        total: this.users.length,
        page: 1,
        page_size: 50,
      });
    const rename = /^\/v1\/admin\/users\/([^/]+)\/rename$/.exec(path);
    if (rename !== null) {
      const user = this.users.find((u) => u.id === rename[1]);
      if (user === undefined) return reply(404, { error: 'not_found' });
      this.renames.push(body);
      // As the Worker does: the letters of a name the account picked itself become a word blocked for everyone.
      const own = !user.renamed && user.username !== null;
      const blocked =
        own && body.block !== false
          ? { term: (user.username ?? '').replace(/[^a-z]/g, ''), kind: 'substring' }
          : null;
      user.username =
        typeof body.username === 'string'
          ? body.username.toLowerCase()
          : `player_${String(user.join).padStart(4, '0')}`;
      user.renamed = true;
      return reply(200, { id: user.id, username: user.username, blocked, block_problem: null });
    }
    if (path === '/v1/admin/moderation') return reply(200, { version: 1, terms: this.terms });
    if (path === '/v1/admin/moderation/terms') {
      this.terms.push({
        term: String(body.term),
        kind: String(body.kind),
        added_at: '2026-10-21T00:00:00Z',
      });
      return reply(200, { term: body.term, kind: body.kind });
    }
    if (path === '/v1/admin/moderation/scan') {
      const term = url.searchParams.get('term') ?? '';
      const matches = this.users
        .filter((u) => u.role === 'user' && u.username?.includes(term) === true)
        .map((u) => ({ id: u.id, username: u.username, join_number: u.join, term }));
      return reply(200, { matches, scanned: this.users.length - 1, next: null });
    }
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

/** The admin: a v1-style key salted by its name, as the deploy runner derives it. */
async function adminUser(): Promise<StubUser> {
  return {
    id: 'a1',
    name: 'Olivia',
    email: null,
    role: 'admin',
    key: await deriveKey(loginSalt('olivia'), PASSWORD),
    emailSalt: null,
    nameKey: null,
    nameSalt: null,
    username: 'olivia',
    join: 1,
    renamed: false,
    schools: [],
  };
}

async function logIn(page: Page, login: string): Promise<void> {
  await page.getByRole('button', { name: 'Sign up or log in' }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('Username or email').fill(login);
  await sheet.getByLabel('Password').fill(PASSWORD);
  await sheet.getByRole('button', { name: 'Log in' }).click();
}

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
    await sheet.getByLabel('Name', { exact: true }).fill('Sam Rivera');
    await sheet.getByLabel('Email', { exact: true }).fill('sam@example.com');
    await sheet.getByLabel('Username', { exact: true }).fill('Sam_Rivera');
    await expect(sheet.getByText('That username is free.')).toBeVisible();
    await sheet.getByLabel('Password', { exact: true }).fill(PASSWORD);
    await sheet.getByLabel('I am 13 or older').check();
    await sheet.getByRole('button', { name: 'Create account' }).click();

    const named = page.getByRole('button', { name: 'Account menu for Sam Rivera' });
    await expect(named).toBeVisible({ timeout: 20_000 });
    if (test.info().project.name === 'desktop') await expect(named).toContainText('Sam');
    // The password itself never left the page: only the key derived from it.
    expect(api.bodies.some((body) => body.includes(PASSWORD))).toBe(false);
    const made = api.users[0];
    expect(made?.username).toBe('sam_rivera');
    expect(made?.key).toBe(await deriveKey(made?.emailSalt ?? '', PASSWORD));
    expect(made?.nameKey).toBe(await deriveKey(made?.nameSalt ?? '', PASSWORD));
    expect(made?.emailSalt).not.toBe(made?.nameSalt);

    await named.click();
    const menu = page.getByRole('menu');
    // The username with its join number in a small box, at the head of the menu.
    await expect(menu.getByLabel('sam_rivera, number 2')).toBeVisible();
    await expect(menu.locator('.join')).toHaveText('#0002');
    await expect(menu.getByRole('menuitem')).toHaveText(['My schools', 'Settings', 'Log out']);
    await menu.getByRole('menuitem', { name: 'Log out' }).click();
    await expect(page.getByRole('button', { name: 'Sign up or log in' })).toBeVisible();
  });

  test('log in, stay logged in on reload, and see no admin view as a user', async ({ page }) => {
    const api = new StubApi();
    api.users.push(
      await stubUser({ id: 'u9', name: 'Jo', email: 'jo@example.com', username: 'jo_snow' }),
    );
    await openPage(page, api, '/?admin');
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    const sheet = page.getByRole('dialog');
    const field = sheet.getByLabel('Username or email');
    await expect(field).toHaveAttribute('autocomplete', 'username');
    await field.fill('Jo@Example.com');
    await sheet.getByLabel('Password').fill('wrong password here');
    await sheet.getByRole('button', { name: 'Log in' }).click();
    await expect(sheet.getByRole('alert')).toHaveText(
      'That username or email and password don’t match an account.',
      { timeout: 20_000 },
    );
    // The same account by its username.
    await field.fill('Jo_Snow');
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

  test('settings offer notifications from a button, never on load, and iPhone Safari gets the guide', async ({
    browser,
  }) => {
    const api = new StubApi();
    const jo = await stubUser({
      id: 'u7',
      name: 'Jo',
      email: 'jo@example.com',
      username: 'jo_snow',
    });
    api.users.push(jo);
    const token = jo.id.padEnd(43, 'x');
    api.sessions.set(token, jo.id);
    const signedIn = (userAgent?: string) =>
      browser.newContext({
        baseURL: ACCOUNTS_URL,
        serviceWorkers: 'block',
        ...(userAgent === undefined ? {} : { userAgent }),
      });
    for (const [userAgent, guide] of [
      [undefined, false],
      [
        'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
        true,
      ],
    ] as const) {
      const context = await signedIn(userAgent);
      await context.addInitScript((held) => {
        localStorage.setItem('snowlight:session', held);
        const counted = window as unknown as { asked: number };
        counted.asked = 0;
        if (typeof Notification !== 'undefined') {
          // Headless Chromium answers "denied" without asking; a browser that was never asked
          // says "default". Every call that would ask the person is counted.
          Object.defineProperty(Notification, 'permission', {
            configurable: true,
            get: () => 'default',
          });
          Notification.requestPermission = () => {
            counted.asked += 1;
            return Promise.resolve('granted');
          };
        }
      }, token);
      const page = await context.newPage();
      const asked: string[] = [];
      page.on('request', (request) => {
        if (request.url().includes('/v1/me/push')) asked.push(request.url());
      });
      await openPage(page, api);
      await page.getByRole('button', { name: 'Account menu for Jo' }).click();
      await page.getByRole('menuitem', { name: 'Settings' }).click();
      const sheet = page.getByRole('dialog');
      await expect(sheet.getByRole('heading', { name: 'Notifications' })).toBeVisible();
      if (guide) {
        await expect(
          sheet.getByText('On iPhone, add Snowlight to your home screen first'),
        ).toBeVisible();
        await expect(sheet.getByRole('button', { name: 'Turn on notifications' })).toHaveCount(0);
      } else {
        await expect(sheet.getByRole('button', { name: 'Turn on notifications' })).toBeVisible();
        // Nothing asked the person for permission on the way here.
        expect(await page.evaluate(() => (window as unknown as { asked: number }).asked)).toBe(0);
      }
      expect(asked).toEqual([]);
      await context.close();
    }
  });

  test('check a username as it is typed, here and then with the API', async ({ page }) => {
    const api = new StubApi();
    api.users.push(
      await stubUser({ id: 'u7', name: 'Ty', email: 'ty@example.com', username: 'taken_name' }),
    );
    await openPage(page, api);
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    await page.getByRole('button', { name: 'New here? Sign up' }).click();
    const field = page.getByRole('dialog').getByLabel('Username', { exact: true });
    const note = page.locator('#username-note');
    await field.fill('ab');
    await expect(note).toHaveText('Use 3 to 20 letters, numbers or underscores.');
    await field.fill('4dm1n');
    await expect(note).toHaveText('That username is reserved. Choose another.');
    await field.fill('snow__day');
    await expect(note).toHaveText(
      'Start and end with a letter or number, with one underscore at a time.',
    );
    await field.fill('taken_name');
    await expect(note).toHaveText('Someone already has that username.');
    await field.fill('fresh_powder');
    await expect(note).toHaveText('That username is free.');
    // The page's own check answered the first three without asking the API.
    const asked = await page.evaluate(() =>
      performance
        .getEntriesByType('resource')
        .map((e) => e.name)
        .filter((n) => n.includes('/v1/usernames/check')),
    );
    expect(asked.every((n) => /taken_name|fresh_powder/.test(n))).toBe(true);
  });

  test('a renamed account picks a new username before anything else', async ({ page }) => {
    const api = new StubApi();
    api.users.push(
      await stubUser({
        id: 'u5',
        name: 'Rae',
        email: 'rae@example.com',
        username: 'player_0005',
        join: 5,
        renamed: true,
      }),
    );
    await openPage(page, api);
    await logIn(page, 'rae@example.com');
    const sheet = page.getByRole('dialog');
    await expect(sheet.getByRole('heading', { name: 'Pick a new username' })).toBeVisible({
      timeout: 20_000,
    });
    await expect(sheet.getByText('Your username was changed. Pick a new one.')).toBeVisible();
    // No way past it but picking one or logging out.
    await expect(sheet.getByRole('button', { name: 'Close' })).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByLabel('Password')).toHaveCount(0);
    await sheet.getByLabel('Username', { exact: true }).fill('rae_of_light');
    await sheet.getByRole('button', { name: 'Save username' }).click();
    await expect(sheet).toHaveCount(0);
    expect(api.users[0]?.username).toBe('rae_of_light');
    await page.getByRole('button', { name: 'Account menu for Rae' }).click();
    await expect(page.getByRole('menu').locator('.join')).toHaveText('#0005');
  });

  test('a v1 account gets fresh keys at its first login, then picks a username', async ({
    page,
  }) => {
    const api = new StubApi();
    api.users.push({
      id: 'u3',
      name: 'Vi',
      email: 'vi@example.com',
      role: 'user',
      key: await deriveKey(loginSalt('vi@example.com'), PASSWORD),
      emailSalt: null,
      nameKey: null,
      nameSalt: null,
      username: null,
      join: 3,
      renamed: false,
      schools: [],
    });
    await openPage(page, api);
    await logIn(page, 'vi@example.com');
    const sheet = page.getByRole('dialog');
    await expect(sheet.getByRole('heading', { name: 'Pick a username' })).toBeVisible({
      timeout: 30_000,
    });
    const vi = api.users[0];
    await expect.poll(() => vi?.emailSalt ?? null).not.toBeNull();
    await expect(sheet.getByLabel('Password')).toHaveCount(0);
    expect(vi?.key).toBe(await deriveKey(vi?.emailSalt ?? '', PASSWORD));
    expect(vi?.nameKey).toBe(await deriveKey(vi?.nameSalt ?? '', PASSWORD));
    await sheet.getByLabel('Username', { exact: true }).fill('vi_v1');
    await sheet.getByRole('button', { name: 'Save username' }).click();
    await expect(sheet).toHaveCount(0);
    expect(api.bodies.some((body) => body.includes(PASSWORD))).toBe(false);
  });

  test('the admin adds a blocked word, sees who it catches and renames them', async ({ page }) => {
    test.skip(test.info().project.name !== 'desktop', 'one screen is enough for the admin view');
    const api = new StubApi();
    api.users.push(await adminUser());
    api.users.push(
      await stubUser({ id: 'u2', name: 'Bo', email: 'bo@example.com', username: 'glitter_bo' }),
    );
    await openPage(page, api, '/?admin');
    await logIn(page, 'Olivia');
    await expect(page.getByRole('heading', { name: 'Admin' })).toBeVisible({ timeout: 20_000 });
    await page.getByRole('tab', { name: 'Moderation' }).click();
    await page.getByLabel('Word or part of a word').fill('glitter');
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByLabel('glitter_bo, number 2')).toBeVisible();
    await page.getByRole('button', { name: 'Rename to a player number' }).click();
    await expect(page.getByText('Renamed', { exact: true })).toBeVisible();
    expect(api.users[1]).toMatchObject({ username: 'player_0002', renamed: true });
    // The word that caught it already blocks it for everyone: no second word.
    expect(api.renames).toEqual([{ block: false }]);

    await page.getByRole('tab', { name: 'Users' }).click();
    await expect(page.getByLabel('player_0002, number 2')).toBeVisible();
    await expect(page.getByText('Picks a new one at next sign-in')).toBeVisible();
    await page.getByRole('button', { name: 'Rename', exact: true }).last().click();
    await page.getByLabel('New username, or empty for a player number').fill('calm_bo');
    await page.getByRole('button', { name: 'Rename', exact: true }).last().click();
    await expect(page.getByLabel('calm_bo, number 2')).toBeVisible();

    // A name the account picked itself: "Also block this word for everyone" is on unless turned off.
    api.users.push(
      await stubUser({
        id: 'u3',
        name: 'Lou',
        email: 'lou@example.com',
        username: 'loud_lou',
        join: 3,
      }),
    );
    await page.getByRole('searchbox', { name: 'Find by name, username or email' }).fill('lou');
    await expect(page.getByLabel('loud_lou, number 3')).toBeVisible();
    await page.getByRole('button', { name: 'Rename', exact: true }).last().click();
    const block = page.getByLabel('Also block this word for everyone');
    await expect(block).toBeChecked();
    await page.getByRole('button', { name: 'Rename', exact: true }).last().click();
    await expect(
      page.getByText(
        'Renamed. Their old name is now blocked for everyone, with any letters or numbers around it.',
      ),
    ).toBeVisible();
    expect(api.renames.at(-1)).toEqual({ block: true });
  });

  test('the sheet and its field stay above the keyboard', async ({ page }) => {
    const phone = test.info().project.name === 'phone';
    // A visual viewport the test can shrink, as an on-screen keyboard does on iPhone Safari
    // and Chrome on Android (the layout viewport stays the same height).
    await page.addInitScript(() => {
      const fake = new EventTarget();
      let height = window.innerHeight;
      Object.defineProperties(fake, {
        height: { get: () => height },
        width: { get: () => window.innerWidth },
        offsetTop: { get: () => 0 },
        offsetLeft: { get: () => 0 },
        pageTop: { get: () => 0 },
        pageLeft: { get: () => 0 },
        scale: { get: () => 1 },
      });
      Object.defineProperty(window, 'visualViewport', { get: () => fake });
      (window as unknown as { keyboard: (h: number) => void }).keyboard = (h) => {
        height = window.innerHeight - h;
        fake.dispatchEvent(new Event('resize'));
      };
    });
    const api = new StubApi();
    await openPage(page, api);
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    await page.getByRole('button', { name: 'New here? Sign up' }).click();
    const sheet = page.getByRole('dialog');
    await page.waitForTimeout(400); // its arrival animation
    const before = await sheet.boundingBox();
    const layout = await page.evaluate(() => window.innerHeight);
    // No keyboard: nothing moves (a desktop never gets one).
    await page.evaluate(() => {
      (window as unknown as { keyboard: (h: number) => void }).keyboard(0);
    });
    await page.waitForTimeout(100);
    expect(await sheet.boundingBox()).toEqual(before);
    if (!phone) return;

    const password = sheet.getByLabel('Password', { exact: true });
    await password.focus();
    const keyboard = Math.round(layout * 0.42);
    await page.evaluate((h) => {
      (window as unknown as { keyboard: (h: number) => void }).keyboard(h);
    }, keyboard);
    const visible = layout - keyboard;
    await expect
      .poll(async () => (await sheet.boundingBox())?.y ?? 0)
      .toBeLessThan((before?.y ?? 0) - 1);
    await page.waitForTimeout(200);
    const box = await sheet.boundingBox();
    const field = await password.boundingBox();
    expect(box && field).toBeTruthy();
    if (box && field) {
      // The sheet ends at the keyboard's top, and the focused field shows inside it.
      expect(Math.abs(box.y + box.height - visible)).toBeLessThanOrEqual(1);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(field.y).toBeGreaterThanOrEqual(box.y);
      expect(field.y + field.height).toBeLessThanOrEqual(visible);
    }
    // Keyboard down: back where it was.
    await page.evaluate(() => {
      (window as unknown as { keyboard: (h: number) => void }).keyboard(0);
    });
    await expect.poll(async () => (await sheet.boundingBox())?.height).toBe(before?.height);
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
    api.users.push(await adminUser());
    await page.clock.install({ time: new Date(at) });
    await api.attach(page);
    await page.goto(`${site}?admin`);
    await page.getByRole('button', { name: 'Sign up or log in' }).click();
    const sheet = page.getByRole('dialog');
    await sheet.getByLabel('Username or email').fill('Olivia');
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

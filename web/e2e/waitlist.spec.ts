import { chromium, expect, test } from '@playwright/test';
import type { Page, Request, Route } from '@playwright/test';

import { waitlistCopy } from '../src/copy-waitlist.ts';
import { copy } from '../src/copy.ts';
import { CODE_VALUE, SUBMIT_TIMEOUT_MS } from '../src/waitlist/gate.ts';
import { WAITLIST_CHROME_URL, WAITLIST_FORM, WAITLIST_URL } from './waitlist-server';

/**
 * The waitlist page, from the build with the waitlist on (playwright.config.ts
 * serves it at WAITLIST_URL), and the usual build beside it, which keeps the
 * code screen. Kit's endpoint is answered here; nothing is ever sent to Kit.
 */

const KIT = `https://app.kit.com/forms/${WAITLIST_FORM}/subscriptions`;
/** The access code, from its stored form, so the code itself is written nowhere in the tests. */
const CODE = atob(CODE_VALUE);

/** Answers Kit's endpoint, and keeps every request it got. */
async function answerKit(
  page: Page,
  answer: (route: Route) => Promise<void> = (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'access-control-allow-origin': '*' },
      body: JSON.stringify({ status: 'success', redirect_url: 'https://app.kit.com/x' }),
    }),
): Promise<Request[]> {
  const sent: Request[] = [];
  await page.route('https://app.kit.com/**', async (route) => {
    sent.push(route.request());
    await answer(route);
  });
  return sent;
}

/** Every request the page makes, by address. */
function recordRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on('request', (request) => urls.push(request.url()));
  return urls;
}

function problems(page: Page): string[] {
  const found: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') found.push(`console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => found.push(`pageerror: ${error.message}`));
  return found;
}

/** The error line the page shows: one of the error block's lines, the others hidden. */
const shownError = (page: Page) => page.locator('#wl-error [data-error]:visible');

const isAppScript = (url: string): boolean =>
  /\/assets\/(?:index|maplibre|basemap)[-.]/.test(new URL(url).pathname);

/** The line on the chances is the waitlist's alone: not in the app's words, nor in a script it loads. */
async function expectNoModelLine(page: Page, urls: readonly string[]): Promise<void> {
  expect(await page.evaluate(() => document.body.innerText)).not.toContain(waitlistCopy.model);
  const scripts = urls.filter((url) => new URL(url).pathname.endsWith('.js'));
  expect(scripts.filter(isAppScript).length).toBeGreaterThan(0);
  for (const url of scripts) {
    expect(await (await page.request.get(url)).text(), url).not.toContain(waitlistCopy.model);
  }
}

test.describe('without VITE_WAITLIST_KIT_FORM', () => {
  test('is the site as before: the code screen, the app script, no waitlist', async ({ page }) => {
    await page.goto('/', { waitUntil: 'load' });
    await expect(page.locator('#waitlist')).toHaveCount(0);
    await expect(page.locator('#lock-form')).toHaveCount(1);
    await expect(page.locator('head script[type="module"][src*="/assets/index-"]')).toHaveCount(1);
    await expect(page.locator('meta[property="og:image"]')).toHaveCount(0);
    await expect(page.locator('main.stage')).toBeVisible();
    await expect(page.getByText(waitlistCopy.model)).toHaveCount(0);
    expect(await (await page.request.get('/')).text()).not.toContain(waitlistCopy.model);
    const privacy = await page.request.get('/privacy.html');
    // The preview server answers unknown paths with the page itself; the build has no privacy page.
    expect(await privacy.text()).not.toContain(waitlistCopy.privacy.intro);
  });
});

test.describe('the waitlist', () => {
  test.use({ baseURL: WAITLIST_URL });

  test('shows the waitlist, asks nothing of any other site and leaves the map unloaded', async ({
    page,
  }) => {
    const errors = problems(page);
    const urls = recordRequests(page);
    await page.goto('/', { waitUntil: 'networkidle' });

    await expect(page).toHaveTitle(waitlistCopy.meta.shareTitle);
    await expect(page.locator('#waitlist h1')).toHaveText(waitlistCopy.headline);
    await expect(page.getByText('Coming this winter.')).toBeVisible();
    // Where the chances come from, under the when line (owner, Oct 26, 2026).
    await expect(page.getByText(waitlistCopy.model, { exact: true })).toBeVisible();
    await expect(page.getByPlaceholder(waitlistCopy.form.email)).toBeVisible();
    await expect(page.getByRole('button', { name: waitlistCopy.form.join })).toBeVisible();
    // The build's Kit form sends a confirmation email first (the default), and the line says so.
    const terms = page.getByText(waitlistCopy.form.termsConfirm);
    await expect(terms).toBeVisible();
    await expect(terms).toContainText('You must be 13 or older.');
    await expect(page.getByText(waitlistCopy.form.terms, { exact: true })).toBeHidden();
    await expect(page.getByRole('link', { name: waitlistCopy.form.privacy })).toBeVisible();
    await expect(page.getByRole('button', { name: waitlistCopy.code.open })).toBeVisible();
    await expect(page.locator('#code-form')).toBeHidden();
    await expect(page.locator('#app')).toBeHidden();

    const origin = new URL(WAITLIST_URL).origin;
    expect(
      urls.filter((url) => !url.startsWith('data:') && new URL(url).origin !== origin),
    ).toEqual([]);
    expect(urls.filter(isAppScript)).toEqual([]);
    expect(urls.filter((url) => url.endsWith('.js'))).toEqual([]);
    // The plain cut for browsers without JavaScript (<noscript>) is text here: no element of it,
    // one waitlist, one form, and none of its pictures fetched a second time.
    await expect(page.locator('noscript *')).toHaveCount(0);
    await expect(page.locator('#waitlist')).toHaveCount(1);
    await expect(page.locator('#waitlist h1')).toHaveCount(1);
    await expect(page.locator('form[action]')).toHaveCount(1);
    const pictures = urls.filter((url) => url.includes('/assets/waitlist/'));
    expect(new Set(pictures).size).toBe(pictures.length);
    // The words are set in the page's own inline cut of Geist: no font file is fetched to swap in.
    expect(urls.filter((url) => /\.woff2?$/.test(new URL(url).pathname))).toEqual([]);
    expect(
      await page.evaluate(async () => {
        await document.fonts.ready;
        return [...document.fonts].some(
          (face) =>
            face.family.replaceAll(/['"]/g, '') === 'Geist Waitlist' && face.status === 'loaded',
        );
      }),
    ).toBe(true);
    expect(
      await page.evaluate(() => 'serviceWorker' in navigator && navigator.serviceWorker.controller),
    ).toBeFalsy();
    expect(errors).toEqual([]);
  });

  test('carries the share card for links', async ({ page }) => {
    await page.goto('/');
    const meta = (selector: string) => page.locator(selector).getAttribute('content');
    expect(await meta('meta[property="og:title"]')).toBe(waitlistCopy.meta.shareTitle);
    expect(await meta('meta[name="description"]')).toBe(waitlistCopy.meta.description);
    expect(await meta('meta[name="twitter:card"]')).toBe('summary_large_image');
    const image = await meta('meta[property="og:image"]');
    expect(image).toMatch(
      /^https:\/\/snowlightmap\.com\/assets\/waitlist\/social\.[0-9a-f]{10}\.jpg$/,
    );
    expect(await meta('meta[name="twitter:image"]')).toBe(image);
    const card = await page.request.get(new URL(image ?? '').pathname);
    expect(card.status()).toBe(200);
    expect(card.headers()['content-type']).toBe('image/jpeg');
    expect(await meta('meta[property="og:image:type"]')).toBe('image/jpeg');
    // Small enough that apps which drop a large link preview still show it.
    expect((await card.body()).byteLength).toBeLessThan(300_000);
  });

  test('lays out once: nothing moves as the page loads', async ({ page }) => {
    await page.addInitScript(() => {
      const shifts: number[] = [];
      Object.assign(window, { __shifts: shifts });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          shifts.push((entry as unknown as { value: number }).value);
        }
      }).observe({ type: 'layout-shift', buffered: true });
    });
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await page.waitForTimeout(500);
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts.reduce((sum, value) => sum + value, 0)).toBe(0);
  });

  test('refuses an address that is not whole, and sends nothing', async ({ page }) => {
    const sent = await answerKit(page);
    await page.goto('/');
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(shownError(page)).toHaveText(waitlistCopy.errors.invalid);
    await expect(page.locator('#wl-email')).toHaveAttribute('aria-invalid', 'true');
    expect(sent).toHaveLength(0);
  });

  test('puts the person on the list, sending Kit the email address alone', async ({ page }) => {
    const sent = await answerKit(page);
    const urls = recordRequests(page);
    await page.goto('/');
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    await page.getByPlaceholder(waitlistCopy.form.email).press('Enter');

    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
    await expect(page.getByText(waitlistCopy.done.title)).toBeHidden();
    await expect(page.getByText(waitlistCopy.done.confirm)).toBeVisible();
    await expect(page.getByText(waitlistCopy.done.noConfirm)).toBeHidden();
    await expect(page.locator('#wl-form')).toBeHidden();
    // The privacy page stays a tap away once the address is given.
    await expect(page.getByRole('link', { name: waitlistCopy.form.privacy })).toBeVisible();
    expect(sent).toHaveLength(1);
    const request = sent[0];
    expect(request?.url()).toBe(KIT);
    expect(request?.method()).toBe('POST');
    expect(request?.headers().accept).toBe('application/json');
    const body = request?.postData() ?? '';
    expect(body).toContain('name="email_address"');
    expect(body).toContain('name@example.com');
    expect(body.match(/name="/g)).toHaveLength(1);
    // The one request that left the site is the signup.
    const origin = new URL(WAITLIST_URL).origin;
    expect(urls.filter((url) => new URL(url).origin !== origin)).toEqual([KIT]);
  });

  test('says it cannot tell whether the signup went through, or that Kit is not taking signups, and lets the person try again', async ({
    page,
  }) => {
    let mode: 'down' | 'server' | 'up' = 'down';
    const sent = await answerKit(page, async (route) => {
      if (mode === 'down') {
        await route.abort('internetdisconnected');
        return;
      }
      await route.fulfill({
        status: mode === 'server' ? 500 : 200,
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify(mode === 'server' ? {} : { status: 'success' }),
      });
    });
    await page.goto('/');
    const email = page.getByPlaceholder(waitlistCopy.form.email);
    const join = page.getByRole('button', { name: waitlistCopy.form.join });
    await email.fill('name@example.com');
    await join.click();
    // The request was on its way when it failed: Kit may have it, so the page says only what it knows.
    await expect(shownError(page)).toHaveText(waitlistCopy.errors.unknown);
    await expect(page.locator('#wl-form')).toBeVisible();

    mode = 'server';
    await join.click();
    await expect(shownError(page)).toHaveText(waitlistCopy.errors.server);
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeHidden();

    mode = 'up';
    await join.click();
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
    expect(sent).toHaveLength(3);
  });

  test('stops waiting for an answer that does not come, and says it cannot tell whether the signup went through', async ({
    page,
  }) => {
    const sent = await answerKit(page, () => new Promise<void>(() => undefined));
    await page.goto('/', { waitUntil: 'load' });
    await page.clock.install();
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(page.locator('#waitlist')).toHaveClass(/is-busy/);
    await page.clock.runFor(SUBMIT_TIMEOUT_MS - 1000);
    await expect(page.locator('#waitlist')).toHaveClass(/is-busy/);
    await expect(shownError(page)).toHaveCount(0);
    await page.clock.runFor(2000);
    await expect(shownError(page)).toHaveText(waitlistCopy.errors.unknown);
    await expect(page.locator('#waitlist')).not.toHaveClass(/is-busy/);
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeHidden();
    expect(sent).toHaveLength(1);
    await page.unrouteAll({ behavior: 'ignoreErrors' });
  });

  test('says the device is offline, and sends nothing, when it has no connection', async ({
    page,
    context,
  }) => {
    const sent = await answerKit(page);
    await page.goto('/', { waitUntil: 'load' });
    await context.setOffline(true);
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(shownError(page)).toHaveText(waitlistCopy.errors.offline);
    expect(sent).toHaveLength(0);
    await context.setOffline(false);
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
    expect(sent).toHaveLength(1);
  });

  test('sends the person to Kit’s check with the page’s strong button when Kit holds the signup', async ({
    page,
  }) => {
    const check = 'https://app.kit.com/forms/1234567/subscriptions/check?id=1';
    await answerKit(page, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify({ status: 'quarantined', url: check }),
      }),
    );
    await page.goto('/');
    await expect(page.locator('.wl-check-link')).toHaveCount(0);
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(page.getByText(waitlistCopy.check.title)).toBeVisible();
    const link = page.getByRole('link', { name: waitlistCopy.check.link });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', check);
    await expect(link).not.toHaveAttribute('target', /./);
    await expect(link).toHaveClass(/wl-join/);
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeHidden();
    await expect(page.getByRole('link', { name: waitlistCopy.form.privacy })).toBeVisible();
  });

  test('sends one signup when the button is pressed again while it is on its way', async ({
    page,
  }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const sent = await answerKit(page, async (route) => {
      await held;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify({ status: 'success' }),
      });
    });
    await page.goto('/');
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    const join = page.locator('.wl-join');
    await join.click();
    await expect(page.locator('#waitlist')).toHaveClass(/is-busy/);
    await expect(page.locator('.wl-joining')).toBeVisible();
    await expect(page.locator('.wl-join-label')).toBeHidden();
    await expect(join).toHaveAttribute('aria-disabled', 'true');
    // A person's second tap lands on the busy button at once; Playwright would wait for
    // an aria-disabled button to be enabled again, so the tap skips that wait.
    await join.click({ force: true });
    await page.getByPlaceholder(waitlistCopy.form.email).press('Enter');
    release();
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
    expect(sent).toHaveLength(1);
  });

  test('opens the code field from the quiet link and the app on the right code', async ({
    page,
  }) => {
    const errors = problems(page);
    const urls = recordRequests(page);
    await page.goto('/', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: waitlistCopy.code.open }).click();
    const field = page.getByPlaceholder(waitlistCopy.code.field);
    await expect(field).toBeFocused();
    // The field's label reads as words; only typed dots are spaced wide.
    const tracking = () => field.evaluate((input) => getComputedStyle(input).letterSpacing);
    expect(await tracking()).toBe('normal');
    await field.fill('1');
    expect(await tracking()).not.toBe('normal');
    await field.fill('');

    await field.fill('1111');
    await field.press('Enter');
    await expect(page.getByText(waitlistCopy.code.wrong)).toBeVisible();
    expect(urls.filter(isAppScript)).toEqual([]);

    await expect(page).toHaveTitle(waitlistCopy.meta.shareTitle);
    await field.fill(CODE);
    await expect(page.locator('#waitlist')).toHaveCount(0);
    // The tab says the app's own name again.
    await expect(page).toHaveTitle(copy.appName);
    await expect(page.locator('main.stage')).toBeVisible();
    await expect(page.locator('.search input')).toBeVisible();
    await expect(page.getByText(waitlistCopy.model)).toHaveCount(0);
    await expect.poll(() => urls.filter(isAppScript).length).toBeGreaterThan(0);
    await expectNoModelLine(page, urls);
    expect(await page.evaluate(() => localStorage.getItem('sl-lock'))).toBe('MjM4MQ==');
    expect(errors).toEqual([]);
  });

  test('takes a device that has entered the code straight to the app, without the waitlist', async ({
    page,
  }) => {
    const urls = recordRequests(page);
    await page.addInitScript(() => {
      localStorage.setItem('sl-lock', 'MjM4MQ==');
      // Whether the waitlist was ever drawn: checked at every frame until the page loads.
      const seen: string[] = [];
      Object.assign(window, { __seen: seen });
      const look = () => {
        const waitlist = document.getElementById('waitlist');
        if (waitlist !== null && getComputedStyle(waitlist).display !== 'none') seen.push('shown');
        if (document.readyState !== 'complete') requestAnimationFrame(look);
      };
      requestAnimationFrame(look);
    });
    const errors = problems(page);
    await page.goto('/', { waitUntil: 'load' });
    await expect(page.locator('#waitlist')).toHaveCount(0);
    await expect(page.locator('main.stage')).toBeVisible();
    await expect(page.locator('html')).toHaveClass(/is-app/);
    await expect(page).toHaveTitle(copy.appName);
    await expect(page.getByText(waitlistCopy.model)).toHaveCount(0);
    await expectNoModelLine(page, urls);
    expect(await page.evaluate(() => (window as unknown as { __seen: string[] }).__seen)).toEqual(
      [],
    );
    // None of the waitlist's pictures is fetched, and the app's script is the first thing asked for.
    expect(urls.filter((url) => url.includes('/assets/waitlist/'))).toEqual([]);
    const fetched = urls.filter((url) => !url.startsWith('data:'));
    expect(fetched[0]).toBe(`${new URL(WAITLIST_URL).origin}/`);
    expect(fetched[1]).toMatch(/\/assets\/index-[\w-]+\.js$/);
    expect(errors).toEqual([]);
  });

  test('shows the chrome wordmark in its held box, says its word, and glints once after load', async ({
    page,
  }) => {
    const urls = recordRequests(page);
    await page.goto('/', { waitUntil: 'load' });
    const hero = page.locator('.wl-hero');
    await expect(hero.locator('.sr-only')).toHaveText(copy.appName);
    await expect(hero.locator('.wl-chrome')).toHaveAttribute('aria-hidden', 'true');
    const image = hero.locator('img');
    await expect(image).toBeVisible();
    expect(
      await image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
    ).toBe(true);
    // Its box is the picture's own shape: width and height attributes hold it before it arrives.
    const box = await image.boundingBox();
    const ratio = await image.evaluate(
      (img: HTMLImageElement) => img.naturalWidth / img.naturalHeight,
    );
    expect(box).not.toBeNull();
    expect(Math.abs((box?.width ?? 0) / (box?.height ?? 1) - ratio)).toBeLessThan(0.02);
    // A phone fetches the phone picture, a wide screen the large one; neither fetches the chrome headline.
    const wide = (page.viewportSize()?.width ?? 0) >= 640;
    const wordmarks = urls.filter((url) => url.includes('/chrome-wordmark'));
    expect(wordmarks).toHaveLength(1);
    expect(wordmarks[0]).toMatch(
      wide ? /chrome-wordmark\.[0-9a-f]{10}\.webp$/ : /chrome-wordmark-small\./,
    );
    expect(urls.filter((url) => url.includes('chrome-headline'))).toEqual([]);
    await expect(page.locator('#waitlist')).toHaveClass(/is-glinting/);
  });

  test('keeps the wordmark still for less motion', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/', { waitUntil: 'load' });
    await page.waitForTimeout(2500);
    await expect(page.locator('#waitlist')).not.toHaveClass(/is-glinting/);
    await expect(page.locator('.wl-glint')).toBeHidden();
    await expect(page.locator('.wl-hero img')).toBeVisible();
  });

  test('removes the service worker and caches an earlier visit to the app left behind', async ({
    page,
  }) => {
    await page.goto('/', { waitUntil: 'load' });
    // As the app did behind the old code screen: its worker, installed, and a cache of its own.
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      await caches.open('snowlight-data-v1');
    });
    const left = () =>
      page.evaluate(async () => ({
        workers: (await navigator.serviceWorker.getRegistrations()).length,
        caches: await caches.keys(),
      }));
    expect((await left()).workers).toBe(1);
    await page.reload({ waitUntil: 'load' });
    await expect(page.locator('#waitlist h1')).toHaveText(waitlistCopy.headline);
    await expect.poll(left).toEqual({ workers: 0, caches: [] });
  });

  test('fits one screen and keeps its words in place through every state', async ({ browser }) => {
    const screens = [
      { width: 1280, height: 720 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
      { width: 1024, height: 768 },
      { width: 390, height: 664 },
      { width: 320, height: 568 },
      // Phones on their side.
      { width: 750, height: 342 },
      { width: 667, height: 375 },
      { width: 844, height: 390 },
      { width: 839, height: 412 },
    ];
    for (const viewport of screens) {
      const context = await browser.newContext({ viewport, baseURL: WAITLIST_URL });
      const page = await context.newPage();
      await answerKit(page);
      await page.goto('/', { waitUntil: 'load' });
      const look = () =>
        page.evaluate(() => {
          const waitlist = document.getElementById('waitlist');
          const top = (selector: string) =>
            Math.round(document.querySelector(selector)?.getBoundingClientRect().top ?? -1);
          return {
            overflow: (waitlist?.scrollHeight ?? 0) - window.innerHeight,
            places: [top('.wl-hero'), top('.wl-title'), top('.wl-act'), top('.wl-foot')],
          };
        });
      const where = `${String(viewport.width)}x${String(viewport.height)}`;
      const empty = await look();
      expect(empty.overflow, `${where} empty`).toBeLessThanOrEqual(0);

      // The access code opens in the form's place, and a wrong one moves nothing either.
      const codeOpen = page.getByRole('button', { name: waitlistCopy.code.open });
      await codeOpen.click();
      const codeField = page.getByPlaceholder(waitlistCopy.code.field);
      await expect(codeField).toBeFocused();
      const code = await look();
      expect(code.overflow, `${where} code`).toBeLessThanOrEqual(0);
      expect(code.places, `${where} code`).toEqual(empty.places);
      await expect(page.getByPlaceholder(waitlistCopy.form.email)).toBeHidden();
      await codeField.fill('1111');
      await codeField.press('Enter');
      await expect(page.getByText(waitlistCopy.code.wrong)).toBeVisible();
      await expect(codeField).toBeInViewport();
      const wrong = await look();
      expect(wrong.overflow, `${where} wrong code`).toBeLessThanOrEqual(0);
      expect(wrong.places, `${where} wrong code`).toEqual(empty.places);
      await codeOpen.click();
      await expect(codeField).toBeHidden();
      await expect(page.getByPlaceholder(waitlistCopy.form.email)).toBeVisible();

      await page.getByPlaceholder(waitlistCopy.form.email).fill('name@');
      await page.getByPlaceholder(waitlistCopy.form.email).press('Enter');
      await expect(shownError(page)).toBeVisible();
      const invalid = await look();
      expect(invalid.overflow, `${where} invalid`).toBeLessThanOrEqual(0);
      expect(invalid.places, `${where} invalid`).toEqual(empty.places);

      await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
      await page.getByPlaceholder(waitlistCopy.form.email).press('Enter');
      await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
      const done = await look();
      expect(done.overflow, `${where} done`).toBeLessThanOrEqual(0);
      expect(done.places, `${where} done`).toEqual(empty.places);
      await context.close();
    }
  });

  test('shows the line on the chances only where it keeps to two lines and the page to one screen', async ({
    browser,
  }) => {
    // Each screen with whether the line shows under the text headline and under the chrome one.
    const screens: { width: number; height: number; text: boolean; chrome: boolean }[] = [
      // Phones: an iPhone, a tall Android, the common small sizes.
      { width: 390, height: 844, text: true, chrome: true },
      { width: 412, height: 915, text: true, chrome: true },
      { width: 375, height: 667, text: true, chrome: false },
      { width: 360, height: 640, text: true, chrome: false },
      // Under 359px wide it could take three lines: an iPhone mini zoomed, a folding phone's cover.
      { width: 352, height: 780, text: false, chrome: false },
      { width: 320, height: 640, text: false, chrome: false },
      { width: 280, height: 653, text: false, chrome: false },
      // Too short to hold it with the form: the smallest iPhone, a height just past the short-screen rules.
      { width: 320, height: 568, text: false, chrome: false },
      { width: 360, height: 648, text: false, chrome: false },
      // Wider windows, a short laptop, and phones on their side.
      { width: 1440, height: 900, text: true, chrome: true },
      { width: 1280, height: 720, text: true, chrome: true },
      { width: 1366, height: 657, text: false, chrome: false },
      { width: 640, height: 600, text: false, chrome: false },
      { width: 800, height: 600, text: false, chrome: false },
      { width: 750, height: 342, text: false, chrome: false },
      { width: 844, height: 390, text: true, chrome: false },
      { width: 932, height: 430, text: true, chrome: true },
    ];
    for (const [headline, url] of [
      ['text', WAITLIST_URL],
      ['chrome', WAITLIST_CHROME_URL],
    ] as const) {
      for (const screen of screens) {
        const { width, height } = screen;
        const where = `${headline} ${String(width)}x${String(height)}`;
        const phone = width < 640;
        const context = await browser.newContext({
          viewport: { width, height },
          baseURL: url,
          hasTouch: phone,
          isMobile: phone,
        });
        const page = await context.newPage();
        await page.goto('/', { waitUntil: 'load' });
        await page.evaluate(() => document.fonts.ready.then(() => undefined));
        const overflow = () =>
          page.evaluate(
            () => (document.getElementById('waitlist')?.scrollHeight ?? 0) - window.innerHeight,
          );
        const line = page.locator('#waitlist .wl-model');
        await expect(line, where).toHaveText(waitlistCopy.model);
        await expect(page.locator('#wl-form'), where).toBeInViewport({ ratio: 1 });
        if (screen[headline]) {
          await expect(line, where).toBeVisible();
          const lines = await line.evaluate(
            (element) =>
              element.getBoundingClientRect().height /
              parseFloat(getComputedStyle(element).lineHeight),
          );
          expect(Math.round(lines), where).toBeLessThanOrEqual(2);
          // Under the when line, and never louder than it.
          const sizes = await page.evaluate(() =>
            ['.wl-when', '.wl-model'].map((selector) => {
              const element = document.querySelector(`#waitlist ${selector}`);
              return element === null ? 0 : parseFloat(getComputedStyle(element).fontSize);
            }),
          );
          expect(sizes[1] ?? 0, where).toBeLessThan(sizes[0] ?? 0);
          // It makes the page scroll no further than it would without it.
          const shown = await overflow();
          await page.addStyleTag({ content: '#waitlist .wl-model { display: none !important; }' });
          expect(shown, where).toBeLessThanOrEqual(Math.max(await overflow(), 0));
        } else {
          await expect(line, where).toBeHidden();
        }
        await context.close();
      }
    }
  });

  test('keeps the line on the chances to two lines on every phone width, with the font hinted or not', async () => {
    // Hinting a font can widen its words by a few percent (it widened them past two lines in CI),
    // so the line is checked in a browser that hints fully as well as in one that does not: at
    // each width where its size steps with the width (359px to 408px), then at its full size on
    // wider phones up to where the wide rules start, where a wider column only leaves more room.
    // Both headlines size the line alike.
    const widths: number[] = [];
    for (let width = 359; width <= 408; width += 1) widths.push(width);
    for (let width = 416; width < 640; width += 16) widths.push(width);
    widths.push(639);
    for (const hinting of ['none', 'full']) {
      const browser = await chromium.launch({ args: [`--font-render-hinting=${hinting}`] });
      const context = await browser.newContext({
        viewport: { width: 390, height: 900 },
        baseURL: WAITLIST_URL,
        hasTouch: true,
        isMobile: true,
      });
      const page = await context.newPage();
      await page.goto('/', { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      const line = page.locator('#waitlist .wl-model');
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        const lines = await line.evaluate(
          (element) =>
            element.getBoundingClientRect().height /
            parseFloat(getComputedStyle(element).lineHeight),
        );
        expect(Math.round(lines), `${hinting} ${String(width)}`).toBe(2);
      }
      await page.setViewportSize({ width: 358, height: 900 });
      await expect(line, `${hinting} 358`).toBeHidden();
      await browser.close();
    }
  });

  test('shows every error in view on a short phone screen, as with its keyboard up', async ({
    browser,
  }) => {
    // 390 x 380: an iPhone's width, and about what stays above its keyboard.
    const context = await browser.newContext({
      viewport: { width: 390, height: 380 },
      baseURL: WAITLIST_URL,
      hasTouch: true,
      isMobile: true,
    });
    const page = await context.newPage();
    let answer: 'rejected' | 'unknown' | 'server' = 'rejected';
    await answerKit(page, async (route) => {
      if (answer === 'unknown') {
        await route.abort('connectionreset');
        return;
      }
      await route.fulfill({
        status: answer === 'server' ? 503 : 200,
        contentType: 'application/json',
        headers: { 'access-control-allow-origin': '*' },
        body: JSON.stringify(
          answer === 'server' ? {} : { status: 'failed', errors: { fields: ['email_address'] } },
        ),
      });
    });
    await page.goto('/', { waitUntil: 'load' });
    const email = page.getByPlaceholder(waitlistCopy.form.email);
    const send = async (kind: string, address: string) => {
      // Back to the top, as on arrival, then the address and the keyboard's Send key.
      await page.evaluate(() => document.getElementById('waitlist')?.scrollTo(0, 0));
      await email.fill(address);
      await email.press('Enter');
      const line = shownError(page);
      await expect(line, kind).toHaveText(
        waitlistCopy.errors[kind as keyof typeof waitlistCopy.errors],
      );
      await expect(line, kind).toBeInViewport({ ratio: 1 });
      // The field stays in view too, to fix the address.
      await expect(email, kind).toBeInViewport();
    };
    await send('invalid', 'name@');
    await expect(email).toBeFocused();
    answer = 'rejected';
    await send('rejected', 'name@example.com');
    await expect(email).toBeFocused();
    await expect(email).toHaveAttribute('aria-invalid', 'true');
    answer = 'unknown';
    await send('unknown', 'name@example.com');
    // Nothing to fix in the address: the keyboard can go, and Join is one press away, and the
    // field is not marked as wrong.
    await expect(page.locator('.wl-join')).toBeFocused();
    await expect(email).not.toHaveAttribute('aria-invalid', /.*/);
    answer = 'server';
    await send('server', 'name@example.com');
    await expect(page.locator('.wl-join')).toBeFocused();
    await expect(email).not.toHaveAttribute('aria-invalid', /.*/);
    await context.setOffline(true);
    await send('offline', 'name@example.com');
    await expect(email).not.toHaveAttribute('aria-invalid', /.*/);
    await context.close();
  });

  test('gives a browser without JavaScript the waitlist, its form posting to Kit itself', async ({
    browser,
  }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, baseURL: WAITLIST_URL });
    const page = await context.newPage();
    const urls = recordRequests(page);
    const sent = await answerKit(page);
    await page.goto('/', { waitUntil: 'load' });
    await expect(page.locator('.wl-hero .sr-only')).toHaveText(copy.appName);
    await expect(page.locator('.wl-hero img')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(waitlistCopy.headline);
    // Playwright's text search skips <noscript>, so these lines are found by their place.
    await expect(page.locator('.wl-when')).toHaveText(waitlistCopy.when);
    await expect(page.locator('.wl-when')).toBeVisible();
    await expect(page.locator('.wl-model')).toHaveText(waitlistCopy.model);
    await expect(page.locator('.wl-model')).toBeVisible();
    const email = page.getByPlaceholder(waitlistCopy.form.email);
    await expect(email).toBeVisible();
    await expect(page.getByRole('button', { name: waitlistCopy.form.join })).toBeVisible();
    const terms = page.locator('.wl-terms [data-confirm="on"]');
    await expect(terms).toHaveText(waitlistCopy.form.termsConfirm);
    await expect(terms).toBeVisible();
    await expect(page.locator('.wl-terms [data-confirm="off"]')).toBeHidden();
    await expect(page.getByRole('link', { name: waitlistCopy.form.privacy })).toBeVisible();
    await expect(page.locator('#app')).toBeHidden();
    const form = page.locator('form[action]');
    await expect(form).toHaveAttribute('action', KIT);
    await expect(form).toHaveAttribute('method', 'post');
    // Nothing leaves the site until the person sends the form.
    const origin = new URL(WAITLIST_URL).origin;
    expect(urls.filter((url) => new URL(url).origin !== origin)).toEqual([]);
    await email.fill('name@example.com');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0]?.method()).toBe('POST');
    expect(sent[0]?.postData()).toBe('email_address=name%40example.com');
    await context.close();
  });

  test('links a plain privacy page', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: waitlistCopy.form.privacy }).click();
    await expect(page).toHaveURL(/\/privacy\.html$/);
    await expect(page.locator('h1')).toHaveText(waitlistCopy.privacy.title);
    await expect(page.getByText(waitlistCopy.privacy.sections.what.body)).toBeVisible();
    // The build's Kit form sends a confirmation email first, and the page says so.
    await expect(page.getByText(waitlistCopy.privacy.sections.why.bodyConfirm)).toBeVisible();
    await expect(page.getByText(waitlistCopy.privacy.sections.why.body)).toBeHidden();
    // No contact address in this build: no line that would need one.
    await expect(page.getByText(waitlistCopy.privacy.sections.remove.contact)).toHaveCount(0);
    await expect(page.getByText(waitlistCopy.privacy.sections.who.body)).toBeVisible();
    // Kit's confirmation email may have no unsubscribe link: the line claims one only after it.
    await expect(page.getByText(waitlistCopy.privacy.sections.remove.bodyConfirm)).toBeVisible();
    await expect(page.getByText(waitlistCopy.privacy.sections.remove.body)).toBeHidden();
    await page.getByRole('link', { name: waitlistCopy.privacy.back }).click();
    await expect(page.locator('#waitlist h1')).toHaveText(waitlistCopy.headline);
  });
});

test.describe('the waitlist with its headline in chrome', () => {
  test.use({ baseURL: WAITLIST_CHROME_URL });

  test('sets the headline in chrome, keeps its words for screen readers, and lays out once', async ({
    page,
  }) => {
    const errors = problems(page);
    const urls = recordRequests(page);
    await page.addInitScript(() => {
      const shifts: number[] = [];
      Object.assign(window, { __shifts: shifts });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          shifts.push((entry as unknown as { value: number }).value);
        }
      }).observe({ type: 'layout-shift', buffered: true });
    });
    await page.goto('/', { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1, name: waitlistCopy.headline })).toHaveCount(
      1,
    );
    const image = page.locator('.wl-title-chrome img');
    await expect(image).toBeVisible();
    expect(
      await image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
    ).toBe(true);
    await expect(page.locator('.wl-title-chrome picture')).toHaveAttribute('aria-hidden', 'true');
    const wide = (page.viewportSize()?.width ?? 0) >= 640;
    const headlines = urls.filter((url) => url.includes('/chrome-headline'));
    expect(headlines).toHaveLength(1);
    expect(headlines[0]).toMatch(
      wide ? /chrome-headline\.[0-9a-f]{10}\.webp$/ : /chrome-headline-small\./,
    );
    const origin = new URL(WAITLIST_CHROME_URL).origin;
    expect(
      urls.filter((url) => !url.startsWith('data:') && new URL(url).origin !== origin),
    ).toEqual([]);
    await page.waitForTimeout(500);
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts.reduce((sum, value) => sum + value, 0)).toBe(0);
    expect(errors).toEqual([]);
  });

  test('puts the person on the list', async ({ page }) => {
    const sent = await answerKit(page);
    await page.goto('/');
    await page.getByPlaceholder(waitlistCopy.form.email).fill('name@example.com');
    await page.getByRole('button', { name: waitlistCopy.form.join }).click();
    await expect(page.getByText(waitlistCopy.done.titleConfirm)).toBeVisible();
    expect(sent).toHaveLength(1);
  });
});

import {
  type Browser,
  type BrowserContext,
  devices,
  expect,
  type Page,
  test,
} from '@playwright/test';

import { getCopy } from '../src/copy-get.ts';
import { GET_URL } from './get-server';

/**
 * The getsnowlight landing (get/, built on its own) and the map's phone redirect to it
 * (index.html, data-get-redirect; docs/getsnowlight.md). The landing's own address,
 * https://www.getsnowlight.com, is answered here from the landing's local server, so the lock
 * sees the address it will have; nothing leaves the machine.
 */
const LANDING = 'https://www.getsnowlight.com/';
const MAP_LINK = 'https://snowlightmap.com/?map=1';
const IPHONE = devices['iPhone 15'];

/** Every request to the landing's address, answered from its local server. */
async function serveLanding(context: BrowserContext): Promise<void> {
  await context.route('https://www.getsnowlight.com/**', async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${GET_URL}${url.pathname}${url.search}` });
    await route.fulfill({ response });
  });
}

/** The map's front page with its redirect switched on, as a build with GET_REDIRECT on writes it. */
function switchedOn(html: string): string {
  // Every e2e build of the map is off (playwright.config.ts VITE_GET_REDIRECT=off).
  expect(html).toContain('data-get-redirect="off"');
  return html.replace('data-get-redirect="off"', 'data-get-redirect="on"');
}

const FRONT = (url: URL) => url.pathname === '/' || url.pathname === '/index.html';

/** The map's own server, with its front page switched on. */
async function switchOn(context: BrowserContext, baseURL: string): Promise<void> {
  const origin = new URL(baseURL).origin;
  await context.route(
    (url) => url.origin === origin && FRONT(url),
    async (route) => {
      if (route.request().resourceType() !== 'document') {
        await route.fallback();
        return;
      }
      const response = await route.fetch();
      await route.fulfill({ response, body: switchedOn(await response.text()) });
    },
  );
}

/**
 * Every request to the map's own address, https://snowlightmap.com, answered from the map's
 * local server, its front page switched on: there the lock's check is the real one.
 */
async function serveMap(context: BrowserContext, baseURL: string): Promise<void> {
  await context.route('https://snowlightmap.com/**', async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${baseURL}${url.pathname}${url.search}` });
    if (route.request().resourceType() === 'document' && FRONT(url)) {
      await route.fulfill({ response, body: switchedOn(await response.text()) });
    } else {
      await route.fulfill({ response });
    }
  });
}

async function iPhone(
  browser: Browser,
  baseURL: string,
  on = true,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    userAgent: IPHONE.userAgent,
    viewport: IPHONE.viewport,
    deviceScaleFactor: IPHONE.deviceScaleFactor,
    isMobile: IPHONE.isMobile,
    hasTouch: IPHONE.hasTouch,
    baseURL,
    serviceWorkers: 'block',
  });
  await serveLanding(context);
  if (on) {
    await switchOn(context, baseURL);
    await serveMap(context, baseURL);
  }
  return { context, page: await context.newPage() };
}

test.describe('the landing', () => {
  test.use({ baseURL: GET_URL });

  test('shows the page, its phones and the live map in place of the App Store badge', async ({
    page,
  }) => {
    const problems: string[] = [];
    page.on('pageerror', (error) => problems.push(error.message));
    page.on('response', (response) => {
      if (response.status() >= 400)
        problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
    });
    await page.goto('/');
    await expect(page).toHaveTitle(getCopy.meta.title);
    await expect(page.locator('h1')).toHaveText(getCopy.hero.title);
    await expect(page.locator('#lock')).toBeHidden();
    const hero = page.locator('header img.phone');
    await expect(hero).toHaveJSProperty('complete', true);
    expect(await hero.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(page.locator('a.badge')).toHaveCount(0);
    await expect(page.getByText(getCopy.soon).first()).toBeVisible();
    const links = page.locator('a[data-map]');
    expect(await links.count()).toBeGreaterThanOrEqual(4);
    for (const href of await links.evaluateAll((all) => all.map((a) => a.getAttribute('href')))) {
      expect(href).toBe(MAP_LINK);
    }
    await expect(page.locator('header a[data-map]').first()).toHaveText(getCopy.openMap);
    // No sideways scroll on a phone or a desktop.
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(problems).toEqual([]);
  });

  test('scrolls to how it works, and opens the Add to Home Screen steps', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: getCopy.hero.how }).click();
    await expect(page).toHaveURL(/#how$/u);
    await expect(page.locator('#how h2')).toBeInViewport();
    const steps = page.locator('#get details');
    await expect(steps.locator('li').first()).toBeHidden();
    await steps.locator('summary').click();
    await expect(steps.locator('li')).toHaveText(Object.values(getCopy.get.homeSteps));
    // Every picture below the top waits until it is near.
    const lazy = await page
      .locator('main img')
      .evaluateAll((all) => all.every((image) => image.getAttribute('loading') === 'lazy'));
    expect(lazy).toBe(true);
  });

  test('is locked on its own address until the code is in', async ({ browser }) => {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await serveLanding(context);
    const page = await context.newPage();
    await page.goto(LANDING);
    await expect(page.locator('#lock')).toBeVisible();
    await expect(page.locator('#lock-input')).toBeFocused();
    await page.locator('#lock-input').fill('0000');
    await page.locator('#lock-input').press('Enter');
    await expect(page.locator('#lock')).toHaveClass(/is-wrong/u);
    await expect(page.locator('#lock')).toBeVisible();
    await context.close();

    // A device that passed the lock before (the value the lock keeps) sees the page.
    const passed = await browser.newContext({ serviceWorkers: 'block' });
    await serveLanding(passed);
    await passed.addInitScript(() => {
      localStorage.setItem('sl-lock', 'MjM4MQ==');
    });
    const open = await passed.newPage();
    await open.goto(LANDING);
    await expect(open.locator('h1')).toBeVisible();
    await expect(open.locator('#lock')).toBeHidden();
    await passed.close();
  });
});

test.describe('the phone redirect', () => {
  test('is off in the e2e build: an iPhone stays on the map', async ({ browser, baseURL }) => {
    const { context, page } = await iPhone(browser, baseURL ?? '', false);
    await page.goto('/');
    await expect(page.locator('main')).toBeAttached();
    expect(new URL(page.url()).host).toBe(new URL(baseURL ?? '').host);
    await context.close();
  });

  test('switched on, sends an iPhone to the landing on every visit until it picks the map', async ({
    browser,
    baseURL,
  }) => {
    const { context, page } = await iPhone(browser, baseURL ?? '');
    await page.goto('/');
    await expect(page).toHaveURL(LANDING);
    await expect(page.locator('h1')).toHaveText(getCopy.hero.title);
    await page.goto(`${baseURL ?? ''}/`);
    await expect(page).toHaveURL(LANDING);

    // The landing's "Open the live map" (?map=1): remembered, taken out of the address bar,
    // and never sent again.
    await page.goto(`${baseURL ?? ''}/?map=1`);
    await expect(page.locator('main')).toBeAttached();
    expect(page.url()).toBe(`${baseURL ?? ''}/`);
    expect(await page.evaluate(() => localStorage.getItem('sl-map'))).toBe('1');
    await page.goto(`${baseURL ?? ''}/`);
    await expect(page.locator('main')).toBeAttached();
    expect(page.url()).toBe(`${baseURL ?? ''}/`);
    await context.close();
  });

  test('switched on, stops the map before it sends: none of the app loads or runs', async ({
    browser,
    baseURL,
  }) => {
    const { context, page } = await iPhone(browser, baseURL ?? '');
    const origin = new URL(baseURL ?? '').origin;
    const asked: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.origin === origin && !FRONT(url)) asked.push(url.pathname);
    });
    const ran: string[] = [];
    page.on('console', (message) => ran.push(message.text()));
    await page.goto('/');
    await expect(page).toHaveURL(LANDING);
    await expect(page.locator('h1')).toHaveText(getCopy.hero.title);
    // The app's data and its later scripts are never asked for; whatever the browser fetched
    // ahead of the page was dropped with it.
    expect(asked.filter((p) => p.startsWith('/data/') || p.includes('maplibre'))).toEqual([]);
    expect(ran).toEqual([]);
    await context.close();
  });

  test('switched on, the Add to Home Screen steps take an iPhone to the map, which keeps it', async ({
    browser,
    baseURL,
  }) => {
    // On the map's own address, past its lock, as an iPhone that has the code.
    const { context, page } = await iPhone(browser, baseURL ?? '');
    await context.addInitScript(() => {
      localStorage.setItem('sl-lock', 'MjM4MQ==');
    });
    await page.goto('https://snowlightmap.com/');
    await expect(page).toHaveURL(LANDING);
    const steps = page.locator('#get details');
    await steps.locator('summary').click();
    await steps.getByRole('link', { name: getCopy.get.homeSteps.open }).click();
    await expect(page).toHaveURL('https://snowlightmap.com/');
    await expect(page.locator('main')).toBeAttached();
    expect(await page.evaluate(() => localStorage.getItem('sl-map'))).toBe('1');
    // The page the next step adds to the Home Screen is the map, and the map stays put.
    await page.reload();
    await expect(page.locator('main')).toBeAttached();
    expect(page.url()).toBe('https://snowlightmap.com/');
    await page.goto('https://snowlightmap.com/');
    await expect(page.locator('main')).toBeAttached();
    expect(page.url()).toBe('https://snowlightmap.com/');
    await context.close();
  });

  test('switched on, never sends a deep link or the home screen', async ({ browser, baseURL }) => {
    const { context, page } = await iPhone(browser, baseURL ?? '');
    for (const path of ['/?school=0100005', '/#school=0100005']) {
      await page.goto(path);
      await expect(page.locator('main')).toBeAttached();
      expect(new URL(page.url()).host, path).toBe(new URL(baseURL ?? '').host);
    }
    await context.close();

    const home = await iPhone(browser, baseURL ?? '');
    await home.context.addInitScript(() => {
      Object.defineProperty(navigator, 'standalone', { value: true });
    });
    await home.page.goto('/');
    await expect(home.page.locator('main')).toBeAttached();
    expect(new URL(home.page.url()).host).toBe(new URL(baseURL ?? '').host);
    await home.context.close();
  });

  test("switched on, never sends this project's own device", async ({ page, baseURL }) => {
    // Desktop Chrome, and the Pixel 7 the phone project runs as.
    await serveLanding(page.context());
    await switchOn(page.context(), baseURL ?? '');
    await page.goto('/');
    await expect(page.locator('main')).toBeAttached();
    expect(new URL(page.url()).host).toBe(new URL(baseURL ?? '').host);
  });
});

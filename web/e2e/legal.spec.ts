/**
 * The privacy policy and the terms of use (src/app/legal.ts, ?privacy and ?terms): behind the
 * lock, word for word as the owner approved them, in the theme's colors at phone and desktop
 * widths, and never on the public waitlist. The links at the foot of Settings are in
 * e2e/accounts.spec.ts, with the accounts build's stand-in API.
 */
import { expect, test, type BrowserContext, type Page } from '@playwright/test';

import { legalCopy, type LegalPageName } from '../src/copy-legal';
import { THEME_STORAGE_KEY } from '../src/theme/event';
import { THEMES } from '../src/theme/themes';
import { approvedWords, words } from '../src/ui/tests/legal-words';

import { WAITLIST_URL } from './waitlist-server';

/** The site's own address, answered from the suite's build: the lock applies there. */
const SITE = 'https://snowlightmap.com/';

/** The value the lock keeps on a device that has entered the code. */
const CODE = ['sl-lock', 'MjM4MQ=='] as const;

const PAGES: readonly LegalPageName[] = ['privacy', 'terms'];

/** Every request to the site's address, answered from the suite's build at `base`. */
async function serveSite(context: BrowserContext, base: string): Promise<void> {
  await context.route(`${SITE}**`, async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${base}${url.pathname}${url.search}` });
    await route.fulfill({ response });
  });
}

/** The page as shown, as words: each heading, paragraph, list item and table cell in order. */
async function shownWords(page: Page): Promise<string> {
  const parts = await page
    .locator('.legal')
    .locator('h1, h2, p, li, th, td')
    .evaluateAll((nodes) => nodes.map((node) => node.textContent));
  return words(parts.join(' '));
}

/** `#rrggbb` as the browser writes a computed color. */
function rgb(hex: string): string {
  const value = Number.parseInt(hex.replace('#', ''), 16);
  return `rgb(${String((value >> 16) & 255)}, ${String((value >> 8) & 255)}, ${String(value & 255)})`;
}

/** Whether the element on top at the middle of the screen is inside `selector`. */
async function onTop(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((inside) => {
    const top = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
    return top?.closest(inside) !== null && top !== null;
  }, selector);
}

test.describe('behind the lock', () => {
  for (const name of PAGES) {
    test(`?${name} shows nothing of the page until the code is in`, async ({
      browser,
      baseURL,
    }) => {
      const context = await browser.newContext({ serviceWorkers: 'block' });
      await serveSite(context, baseURL ?? '');
      const page = await context.newPage();
      await page.goto(`${SITE}?${name}`);
      await expect(page.locator('#lock')).toBeVisible();
      // Whatever the app has drawn by now lies under the lock, and nothing of the page is in it:
      // not drawn, not read out, and not holding the keyboard.
      await page.waitForTimeout(2500);
      expect(await onTop(page, '#lock')).toBe(true);
      await expect(page.locator('.legal')).toHaveCount(0);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.getByText(legalCopy.pages[name].title, { exact: true })).toHaveCount(0);
      await expect(page.locator('#lock-input')).toBeFocused();
      await page.keyboard.type('9');
      await expect(page.locator('#lock-input')).toHaveValue('9');
      await context.close();
    });
  }

  test('?privacy shows the page asked for once the right code is typed in', async ({
    browser,
    baseURL,
  }) => {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await serveSite(context, baseURL ?? '');
    const page = await context.newPage();
    await page.goto(`${SITE}?privacy`);
    await expect(page.locator('#lock-input')).toBeFocused();
    await page.waitForTimeout(1500);
    // Typed as a person types it: the code screen takes it as the last digit goes in.
    await page.keyboard.type(atob(CODE[1]));
    await expect(page.locator('#lock')).toBeHidden();
    const doc = legalCopy.pages.privacy;
    await expect(
      page.getByRole('dialog', { name: doc.title }).getByRole('heading', { level: 1 }),
    ).toHaveText(doc.title);
    await expect(page.locator('#legal-title')).toBeFocused();
    await context.close();
  });

  for (const name of PAGES) {
    test(`?${name} shows the approved words, on top, once the code is in`, async ({
      browser,
      baseURL,
    }) => {
      const context = await browser.newContext({ serviceWorkers: 'block' });
      await serveSite(context, baseURL ?? '');
      await context.addInitScript(([key, value]) => {
        localStorage.setItem(key, value);
      }, CODE);
      const page = await context.newPage();
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(`${SITE}?ref=e2e&${name}`);
      await expect(page.locator('#lock')).toBeHidden();
      const doc = legalCopy.pages[name];
      const dialog = page.getByRole('dialog', { name: doc.title });
      await expect(dialog.getByRole('heading', { level: 1 })).toHaveText(doc.title);
      await expect(dialog).toContainText('hello@snowlightmap.com');
      expect(await shownWords(page)).toBe(approvedWords(name));
      expect(await onTop(page, '.legal')).toBe(true);
      // Phone or desktop: nothing runs off the side.
      const fits = await page.evaluate(() => {
        const legal = document.querySelector('.legal');
        return (
          document.documentElement.scrollWidth <= innerWidth &&
          legal !== null &&
          legal.scrollWidth <= legal.clientWidth
        );
      });
      expect(fits).toBe(true);
      // Escape closes it, and the address keeps everything but the page.
      await page.keyboard.press('Escape');
      await expect(page.locator('.legal')).toHaveCount(0);
      expect(new URL(page.url()).search).toBe('?ref=e2e');
      expect(errors).toEqual([]);
      await context.close();
    });
  }

  test('takes the theme’s colors: Midnight and Daylight', async ({ browser, baseURL }) => {
    for (const id of ['midnight', 'daylight'] as const) {
      const context = await browser.newContext({ serviceWorkers: 'block' });
      await serveSite(context, baseURL ?? '');
      await context.addInitScript(
        ([key, value, themeKey, theme]) => {
          localStorage.setItem(key, value);
          localStorage.setItem(themeKey, theme);
        },
        [...CODE, THEME_STORAGE_KEY, JSON.stringify({ id })] as const,
      );
      const page = await context.newPage();
      await page.goto(`${SITE}?privacy`);
      const legal = page.locator('.legal');
      await expect(legal.locator('h1')).toBeVisible();
      await expect
        .poll(() => legal.evaluate((node) => getComputedStyle(node).backgroundColor))
        .toBe(rgb(THEMES[id].tokens.bg));
      expect(await legal.locator('h1').evaluate((node) => getComputedStyle(node).color)).toBe(
        rgb(THEMES[id].tokens.text1),
      );
      await context.close();
    }
  });
});

test.describe('the public waitlist', () => {
  test.use({ baseURL: WAITLIST_URL });

  for (const name of PAGES) {
    test(`?${name} shows the waitlist and never loads the page without the code`, async ({
      page,
    }) => {
      const scripts: string[] = [];
      page.on('request', (request) => {
        if (new URL(request.url()).pathname.endsWith('.js')) scripts.push(request.url());
      });
      await page.goto(`/?${name}`, { waitUntil: 'networkidle' });
      await expect(page.locator('#waitlist')).toBeVisible();
      await expect(page.locator('.legal')).toHaveCount(0);
      const intro = legalCopy.pages[name].blocks[0];
      expect(intro !== undefined && 'p' in intro).toBe(true);
      if (intro !== undefined && 'p' in intro) {
        expect(await page.evaluate(() => document.body.innerText)).not.toContain(intro.p);
        expect(await page.content()).not.toContain(intro.p);
      }
      expect(scripts.filter((url) => /\/assets\/(?:index|LegalPage|boot)-/u.test(url))).toEqual([]);
    });
  }

  test('?terms shows the terms to a device that has the code', async ({ page }) => {
    await page.addInitScript(([key, value]) => {
      localStorage.setItem(key, value);
    }, CODE);
    await page.goto('/?terms');
    await expect(page.locator('#waitlist')).toHaveCount(0);
    await expect(
      page.getByRole('dialog', { name: legalCopy.pages.terms.title }).locator('h1'),
    ).toHaveText(legalCopy.pages.terms.title);
    expect(await shownWords(page)).toBe(approvedWords('terms'));
  });
});

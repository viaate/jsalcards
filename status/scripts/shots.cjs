/**
 * Takes the status page's proof pictures from the preview server (`node scripts/preview.mjs`)
 * and checks each state: no layout shift and no box that moved or grew from load to data, no
 * horizontal scroll (at 320 px too), no console error, no request leaving the origin. Fails if
 * any check does.
 *
 *   NODE_PATH=../web/node_modules node scripts/shots.cjs [out folder]
 *
 * Playwright is the website's, not a dependency here, and no CI job runs this.
 */

const { mkdirSync } = require('node:fs');
const { join } = require('node:path');
const { chromium } = require('playwright');

const ORIGIN = 'http://127.0.0.1:4190';
const out = process.argv[2] ?? join(__dirname, '..', 'shots');

const PHONE = { width: 390, height: 844, scale: 2 };
const DESKTOP = { width: 1280, height: 800, scale: 1 };
const NARROW = { width: 320, height: 640, scale: 1 };

/** [file, state, scheme, viewport]; a null file is checked and not saved. */
const SHOTS = [
  ['history-light-phone', 'history', 'light', PHONE],
  ['history-dark-phone', 'history', 'dark', PHONE],
  ['history-light-desktop', 'history', 'light', DESKTOP],
  ['history-dark-desktop', 'history', 'dark', DESKTOP],
  ['first-dark-phone', 'first', 'dark', PHONE],
  ['unreachable-light-phone', 'unreachable', 'light', PHONE],
  ['stale-dark-desktop', 'stale', 'dark', DESKTOP],
  ['ok-light-desktop', 'ok', 'light', DESKTOP],
  ['history-light-320', 'history', 'light', NARROW],
  [null, 'ok', 'light', NARROW],
  [null, 'first', 'light', NARROW],
  [null, 'stale', 'light', NARROW],
  [null, 'unreachable', 'light', NARROW],
  ['worst-light-320', 'worst', 'light', NARROW],
  ['worst-light-phone', 'worst', 'light', PHONE],
  [null, 'worst', 'light', DESKTOP],
];

/** Where each box that fills from data sits, so a box that grew or moved can be told. */
function boxes(page) {
  return page.evaluate(() => {
    const picked = 'main > section, .banner, .row, .hist, .probs, .more-row, footer';
    return [...document.querySelectorAll(picked)].map((box) => {
      const rect = box.getBoundingClientRect();
      const top = Math.round((rect.top + window.scrollY) * 10) / 10;
      return `${box.classList[0] ?? box.tagName.toLowerCase()} ${top} ${Math.round(rect.height * 10) / 10}`;
    });
  });
}

function moved(before, after) {
  if (before.length !== after.length) return `${before.length} boxes became ${after.length}`;
  const at = before.findIndex((box, i) => box !== after[i]);
  return at < 0 ? null : `"${before[at]}" became "${after[at]}"`;
}

async function one(browser, [file, state, scheme, viewport]) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.scale,
    colorScheme: scheme,
    timezoneId: 'America/New_York',
    locale: 'en-US',
  });
  const page = await context.newPage();
  const problems = [];
  page.on('console', (message) => {
    // A made-up state that does not answer gives 503 on purpose: the browser logs that fetch.
    if (message.type() !== 'error') return;
    if ((state === 'unreachable' || state === 'worst') && message.text().includes('503')) return;
    problems.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => problems.push(`error: ${error.message}`));
  page.on('request', (request) => {
    if (!request.url().startsWith(`${ORIGIN}/`)) problems.push(`left the origin: ${request.url()}`);
  });
  await page.clock.install();
  await page.addInitScript(() => {
    window.__shift = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries())
        if (!entry.hadRecentInput) window.__shift += entry.value;
    }).observe({ type: 'layout-shift', buffered: true });
  });
  await (await context.request.get(`${ORIGIN}/__set?state=${state}`)).text();
  // The first answer is held back until the "Checking" page has been measured.
  let release;
  const held = new Promise((resolve) => (release = resolve));
  await page.route('**/api/status', async (route) => {
    await held;
    await route.continue();
  });
  await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
  const before = await boxes(page);
  release();
  await page.waitForFunction(
    () => !document.querySelector('.lead')?.textContent?.includes('Checking'),
  );
  await page.waitForTimeout(300);
  let after = await boxes(page);
  let change = moved(before, after);
  if (change !== null) problems.push(`moved from load to data: ${change}`);
  if (state === 'worst') {
    // A refresh that fails keeps the page and says so, in the banner's longest last line.
    await (await context.request.get(`${ORIGIN}/__set?state=unreachable`)).text();
    await page.clock.fastForward(400000);
    await page.waitForFunction(() =>
      document.querySelector('.more')?.textContent?.includes('Could not refresh'),
    );
    after = await boxes(page);
    change = moved(before, after);
    if (change !== null) problems.push(`moved when a refresh failed: ${change}`);
  }
  const measured = await page.evaluate(() => ({
    shift: window.__shift,
    scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  }));
  if (measured.shift !== 0) problems.push(`layout shift ${measured.shift}`);
  if (measured.scroll > 0) problems.push(`horizontal scroll ${measured.scroll}px`);
  if (state === 'history' || state === 'worst') {
    // Point at a day with trouble, so the note line is in the picture and is measured too.
    const bars = page.locator('.bars[data-part="closings"]');
    await bars.scrollIntoViewIfNeeded();
    const box = await bars.boundingBox();
    const day = state === 'history' ? 79.5 : 67.5;
    await page.mouse.move(box.x + (box.width * day) / 90, box.y + box.height / 2);
    await page.waitForFunction(() =>
      document.querySelector('.note')?.parentElement?.parentElement?.textContent?.includes(':'),
    );
    change = moved(before, await boxes(page));
    if (change !== null) problems.push(`moved when a day was picked: ${change}`);
    await page.mouse.move(0, 0);
  }
  if (file !== null) await page.screenshot({ path: join(out, `${file}.png`), fullPage: true });
  await context.close();
  const name = `${file ?? '(no picture)'} ${state} ${scheme} ${viewport.width}x${viewport.height}`;
  console.log(
    `${problems.length === 0 ? 'ok  ' : 'FAIL'} ${name}: layout shift ${measured.shift}, ` +
      `horizontal scroll ${Math.max(0, measured.scroll)} px` +
      (problems.length === 0
        ? ', no box moved, no console error, no request off the origin'
        : `; ${problems.join('; ')}`),
  );
  return problems.length === 0;
}

(async () => {
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  let good = true;
  for (const shot of SHOTS) good = (await one(browser, shot)) && good;
  await browser.close();
  process.exit(good ? 0 : 1);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

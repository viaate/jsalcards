/**
 * Takes the status page's proof pictures from the preview server (`node scripts/preview.mjs`)
 * and checks each state: no layout shift and no box that moved or grew from load to data, no
 * horizontal scroll (at 320 px too), no console error, no request leaving the origin. Then
 * checks of their own: at nine widths from 320 to 1280 px, in every state, no line breaks
 * inside a name, a date, a time or a count, and no visible text ends in a line of one word;
 * with scripts off only the line that says so is shown; a page whose script never loads stops saying "Checking" after 10 s and moves nothing; coming back to the tab with
 * an old answer says its age at once, before any fetch settles; and with text at 150% on a
 * 320 px screen nothing scrolls sideways. Fails if any check does.
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
  ['stale-light-320', 'stale', 'light', NARROW],
  ['unreachable-light-320', 'unreachable', 'light', NARROW],
  ['worst-light-320', 'worst', 'light', NARROW],
  ['worst-light-phone', 'worst', 'light', PHONE],
  [null, 'worst', 'light', DESKTOP],
  ['launch-light-phone', 'launch', 'light', PHONE],
  ['ok-light-phone', 'ok', 'light', PHONE],
  [null, 'launch', 'light', NARROW],
  [null, 'launch', 'dark', DESKTOP],
];

/** The widths the line breaks are checked at: the common phones, a tablet, a desktop. */
const WIDTHS = [320, 360, 375, 390, 393, 412, 430, 768, 1280];

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
    await page.waitForFunction(() => document.querySelector('.note:not(.hint)') !== null);
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

function said(good, name, detail) {
  console.log(`${good ? 'ok  ' : 'FAIL'} ${name}: ${detail}`);
  return good;
}

/**
 * What one look at the page finds: each tied run (a joiner or a no-break space and no breaking
 * space) drawn on more than one line, and each text of more than one line whose last line is a
 * word alone. Every visible text is looked at: the banner, the rows, the shares, the notes, the
 * problems, the key and the footer.
 */
function looked() {
  const split = [];
  const lone = [];
  let tied = 0;
  let texts = 0;
  /** The tops of the lines a stretch of a text node is drawn on. */
  const tops = (node, from, to) => {
    const range = document.createRange();
    range.setStart(node, from);
    range.setEnd(node, to);
    return [...new Set([...range.getClientRects()].map((rect) => Math.round(rect.top)))];
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (parent === null || parent.closest('.sr, script, style, noscript') !== null) continue;
    if (parent.getClientRects().length === 0 || node.data.trim() === '') continue;
    texts += 1;
    for (const match of node.data.matchAll(/[^ \n]*[\u2060\u00a0][^ \n]*/g)) {
      tied += 1;
      if (tops(node, match.index, match.index + match[0].length).length > 1)
        split.push(`"${match[0]}" in "${node.data}"`);
    }
    // A word as the reader counts it: "60 days." on a line is two words, held together.
    const words = [...node.data.matchAll(/[^ \n\u00a0]+/g)];
    const lines = new Map();
    for (const word of words) {
      const top = tops(node, word.index, word.index + word[0].length)[0];
      lines.set(top, (lines.get(top) ?? 0) + 1);
    }
    const counts = [...lines.values()];
    if (counts.length > 1 && counts[counts.length - 1] === 1)
      lone.push(`"${node.data}" (${parent.className || parent.tagName.toLowerCase()})`);
  }
  return { split, lone, tied, texts };
}

/**
 * At each width, in a state: a name, a date, a time or a count is drawn on one line (each is
 * tied in the words themselves, with a word joiner or a no-break space), and no visible text
 * ends in a line of one word. Looked at as it opens, with every problem shown, and again with a
 * bar picked where there are bars to pick.
 */
async function lineBreaks(browser, state) {
  const found = [];
  let texts = 0;
  for (const width of WIDTHS) {
    const context = await browser.newContext({
      viewport: { width, height: 900 },
      timezoneId: 'America/New_York',
      locale: 'en-US',
    });
    const page = await context.newPage();
    await (await context.request.get(`${ORIGIN}/__set?state=${state}`)).text();
    await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
    await page.waitForFunction(
      () => !document.querySelector('.lead')?.textContent?.includes('Checking'),
    );
    if ((await page.locator('#more').count()) > 0) await page.locator('#more').click();
    const seen = [await page.evaluate(looked)];
    const bars = page.locator('.bars[data-part="closings"]:not([aria-hidden="true"])');
    if ((await bars.count()) > 0) {
      await bars.scrollIntoViewIfNeeded();
      const box = await bars.boundingBox();
      await page.mouse.move(box.x + (box.width * 79.5) / 90, box.y + box.height / 2);
      await page.waitForFunction(() => document.querySelector('.note:not(.hint)') !== null);
      seen.push(await page.evaluate(looked));
    }
    await context.close();
    if (seen.every((one) => one.tied === 0)) found.push(`${width} px: nothing tied was found`);
    for (const one of seen) {
      texts += one.texts;
      for (const text of one.split) found.push(`${width} px: split ${text}`);
      for (const text of one.lone) found.push(`${width} px: a last line of one word in ${text}`);
    }
  }
  return said(
    found.length === 0,
    `line breaks ${state}`,
    found.length === 0
      ? `${texts} texts: no name, date, time or count split and no one-word last line at ` +
          `${WIDTHS.join(', ')} px`
      : found.join('; '),
  );
}

/**
 * The script never loads (scripts are on). For 10 s the page says "Checking"; then the
 * stylesheet alone draws the line that says the page did not finish loading, in the same
 * place, and the rows stop saying "Checking". No box moves.
 */
async function scriptMissing(browser) {
  const context = await browser.newContext({
    viewport: { width: PHONE.width, height: PHONE.height },
    deviceScaleFactor: PHONE.scale,
  });
  const page = await context.newPage();
  await page.route('**/app.js', (route) => route.abort());
  await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
  const look = () =>
    page.evaluate(() => {
      const shown = (box) => getComputedStyle(box).visibility === 'visible';
      return {
        lead: shown(document.querySelector('.lead:not(.stuck)')),
        stuck: shown(document.querySelector('.stuck')),
        states: [...document.querySelectorAll('.state')].filter(shown).length,
        line: document.querySelector('.stuck').textContent,
      };
    });
  const first = await look();
  const before = await boxes(page);
  await page.waitForTimeout(10500);
  const then = await look();
  const change = moved(before, await boxes(page));
  await page.screenshot({ path: join(out, 'script-missing-light-phone.png'), fullPage: true });
  await context.close();
  return said(
    first.lead &&
      !first.stuck &&
      first.states === 4 &&
      !then.lead &&
      then.stuck &&
      then.states === 0 &&
      change === null,
    'script-missing-light-phone',
    `at load "Checking" is shown (${first.states} rows); after 10 s "${then.line}" is shown in ` +
      `its place, ${then.states} rows say "Checking"` +
      (change === null ? ', no box moved' : `; moved: ${change}`),
  );
}

/** With scripts off the boxes cannot fill in: only the header, the line that says so, the footer. */
async function scriptsOff(browser) {
  const context = await browser.newContext({
    viewport: { width: PHONE.width, height: PHONE.height },
    deviceScaleFactor: PHONE.scale,
    javaScriptEnabled: false,
  });
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
  const seen = await page.evaluate(() => ({
    main: document.getElementById('main').getBoundingClientRect().height,
    line: document.querySelector('.noscript')?.textContent ?? '',
    how: document.querySelector('.how').getBoundingClientRect().height,
    checking: [...document.querySelectorAll('.lead, .state')].some(
      (box) => box.getBoundingClientRect().height > 0,
    ),
  }));
  await page.screenshot({ path: join(out, 'scripts-off-light-phone.png'), fullPage: true });
  await context.close();
  return said(
    seen.main === 0 && seen.how === 0 && !seen.checking && seen.line !== '',
    'scripts-off-light-phone',
    `main is ${seen.main} px tall and the footer's line about the bars ${seen.how} px, ` +
      `"${seen.line}" is shown, no "Checking" box is drawn`,
  );
}

/** Back on a tab whose answer is 20 minutes old, with the network gone: the age is said at once. */
async function comingBack(browser) {
  const context = await browser.newContext({ viewport: NARROW, timezoneId: 'America/New_York' });
  const page = await context.newPage();
  await page.clock.install();
  await (await context.request.get(`${ORIGIN}/__set?state=ok`)).text();
  await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
  await page.waitForFunction(() =>
    document.querySelector('.lead')?.textContent?.includes('Everything is working'),
  );
  // From here no fetch ever settles, and the device's clock jumps without any timer firing.
  await page.route('**/api/status', () => new Promise(() => {}));
  await page.clock.setSystemTime(Date.now() + 20 * 60 * 1000);
  const seen = await page.evaluate(() => {
    const before = document.querySelector('.lead').textContent;
    window.dispatchEvent(new Event('pageshow'));
    const shown = document.querySelector('.lead').textContent;
    document.dispatchEvent(new Event('visibilitychange'));
    return {
      before,
      shown,
      states: [...document.querySelectorAll('.state')].map((s) => s.textContent),
    };
  });
  await context.close();
  return said(
    seen.before === 'Everything is working.' &&
      seen.shown === 'We have no recent checks.' &&
      seen.states.every((state) => state === 'Could not check'),
    'coming back to the tab',
    `"${seen.before}" became "${seen.shown}" in the same task as pageshow, rows: ${[...new Set(seen.states)].join(', ')}`,
  );
}

/** Text at 150% on a 320 px screen: every box wraps, nothing scrolls sideways. */
async function bigText(browser, state) {
  // The larger text is set by a style of the test's own, which the page's policy would refuse.
  const context = await browser.newContext({ viewport: NARROW, bypassCSP: true });
  const page = await context.newPage();
  await (await context.request.get(`${ORIGIN}/__set?state=${state}`)).text();
  await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
  await page.addStyleTag({ content: 'html { font-size: 150%; }' });
  await page.waitForFunction(
    () => !document.querySelector('.lead')?.textContent?.includes('Checking'),
  );
  await page.waitForTimeout(200);
  const seen = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const wide = [...document.querySelectorAll('body *')]
      .filter((box) => box.getBoundingClientRect().right > width + 0.5 && !box.closest('.sr'))
      .map((box) => `${box.tagName.toLowerCase()}.${box.className}`);
    return { scroll: document.documentElement.scrollWidth - width, wide: [...new Set(wide)] };
  });
  await page.screenshot({ path: join(out, `big-text-${state}-320.png`), fullPage: true });
  await context.close();
  return said(
    seen.scroll <= 0 && seen.wide.length === 0,
    `big-text-${state}-320`,
    `horizontal scroll ${Math.max(0, seen.scroll)} px` +
      (seen.wide.length === 0
        ? ', no box past the edge'
        : `; past the edge: ${seen.wide.join(' ')}`),
  );
}

(async () => {
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  let good = true;
  for (const shot of SHOTS) good = (await one(browser, shot)) && good;
  for (const state of ['history', 'worst', 'launch', 'ok', 'stale', 'first', 'unreachable'])
    good = (await lineBreaks(browser, state)) && good;
  good = (await scriptsOff(browser)) && good;
  good = (await scriptMissing(browser)) && good;
  good = (await comingBack(browser)) && good;
  for (const state of ['history', 'worst', 'first', 'unreachable'])
    good = (await bigText(browser, state)) && good;
  await browser.close();
  process.exit(good ? 0 : 1);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});

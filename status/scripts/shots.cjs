/**
 * Takes the status page's proof pictures from the preview server (`node scripts/preview.mjs`)
 * and checks each state: no layout shift and no box that moved or grew from load to data, no
 * horizontal scroll (at 320 px too), no console error, no request leaving the origin. Then
 * checks of their own: with scripts off only the line that says so is shown; a page whose
 * script never loads stops saying "Checking" after 10 s and moves nothing; coming back to the
 * tab with an old answer says its age at once, before any fetch settles; and in every state,
 * at nine widths from 320 to 1280 px and at text of 100%, 150% and 200%, with every problem
 * shown and with a bar picked: the banner's headline is never smaller than the body text or
 * its usual size and always larger than the line under it; nothing scrolls sideways and no
 * element or text reaches past the box it is in; the axis labels keep half a line apart or
 * "Today" goes down a line under the last bar; the banner holds its words in its reserve; no
 * line breaks inside a part's name (read from the copy, whatever its spaces), a date, a time,
 * a length or a count, except a box wider than its whole line, which breaks between its parts;
 * and no visible text ends in a line of one word. Fails if any check does.
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
  ['worst-light-desktop', 'worst', 'light', DESKTOP],
  [null, 'worst', 'dark', { width: 768, height: 1024, scale: 1 }],
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
 * The runs that must sit on one line however the copy spells their spaces: each part's name,
 * as `page/src/copy.ts` has it, and the few words that read wrong apart. Filled in at start.
 */
let WHOLE = [];
async function wholeRuns() {
  const { copy } = await import('../page/src/copy.ts');
  const plain = (text) => text.replace(/\u00a0/g, ' ').replace(/\u2060/g, '');
  return [...Object.values(copy.parts).map((part) => plain(part.name)), 'at least', 'right now'];
}

/**
 * What one look at the page finds.
 *
 * - split: a box (a part's name, a date, a time, a length, an address) drawn on more than one
 *   line though it fits on one, and a tied run (a joiner or a no-break space) or one of `whole`
 *   (with any spaces) drawn on more than one line. A box wider than its whole line may break:
 *   between its parts where it has parts ("23 hours" and "55 minutes."), and that is counted.
 * - lone: a text of more than one line whose last line is a word alone (with `big`, of three
 *   words or more), across its boxes, where wrapping could have avoided it: the word or box at
 *   the end of the line above and the word alone fit on one line. Where they do not (very large
 *   text on a narrow phone), it is counted as `alone`.
 * - spill: an element, or a text, that reaches past the sides of the box it is in.
 * - axis: the two labels under the bars closer than half a line, or "Today" not ending under
 *   the last bar.
 * - grew: the banner taller than its reserve, which would move the page when it fills.
 *
 * Every visible text is looked at: the banner, the rows, the shares, the notes, the problems,
 * the key and the footer.
 */
function looked({ whole, big }) {
  const split = [];
  const lone = [];
  const spill = [];
  const axis = [];
  let tied = 0;
  let texts = 0;
  let wider = 0;
  let alone = 0;
  const BOX = '.nm, .nb';
  const shown = (el) =>
    el.getClientRects().length > 0 &&
    getComputedStyle(el).visibility === 'visible' &&
    el.closest('.sr, script, style, noscript') === null;
  /** The tops of the lines a stretch of a text node is drawn on. */
  const tops = (node, from, to) => {
    const range = document.createRange();
    range.setStart(node, from);
    range.setEnd(node, to);
    return [...new Set([...range.getClientRects()].map((rect) => Math.round(rect.top)))];
  };
  /** The text nodes in an element, in order. */
  const textsIn = (el) => {
    const found = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode())
      if (node.data.length > 0) found.push(node);
    return found;
  };
  const linesOf = (el) => [...new Set(textsIn(el).flatMap((n) => tops(n, 0, n.data.length)))];
  /** The outermost box an element is in, or null. */
  const outer = (el) => {
    let box = el.closest(BOX);
    while (box?.parentElement?.closest(BOX)) box = box.parentElement.closest(BOX);
    return box;
  };
  /**
   * A box that cannot fit on one line: on one line it would be wider than it is, and it already
   * takes its whole line (the width of what it is in).
   */
  const wide = (box) => {
    if (box === null || box.parentElement === null) return false;
    const width = box.getBoundingClientRect().width;
    const line = box.parentElement.getBoundingClientRect().width;
    box.style.inlineSize = 'max-content';
    const whole = box.getBoundingClientRect().width;
    box.style.inlineSize = '';
    return whole - width > 0.05 && width >= line - 1;
  };
  const owners = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (parent === null || !shown(parent) || node.data.trim() === '') continue;
    texts += 1;
    for (const match of node.data.matchAll(/[^ \n]*[\u2060\u00a0][^ \n]*/g)) {
      tied += 1;
      if (tops(node, match.index, match.index + match[0].length).length > 1)
        split.push(`"${match[0]}" in "${node.data}"`);
    }
    for (const run of whole) {
      const spaced = run
        .split(' ')
        .map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/-/g, '-\u2060?'))
        .join('[ \u00a0\n]+');
      for (const match of node.data.matchAll(new RegExp(spaced, 'g'))) {
        tied += 1;
        if (tops(node, match.index, match.index + match[0].length).length <= 1) continue;
        // A name's box breaks only when it is wider than the whole line: that is the one split
        // allowed, and it is counted. Anywhere else, a split is a fault.
        if (wide(parent.closest(BOX))) wider += 1;
        else split.push(`"${run}" in "${node.data}"`);
      }
    }
    // A text drawn past the sides of its element.
    const box = parent.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(node);
    for (const rect of range.getClientRects())
      if (rect.width > 0 && (rect.left < box.left - 0.5 || rect.right > box.right + 0.5))
        spill.push(
          `text "${node.data.trim()}" past its ${parent.tagName.toLowerCase()}.${parent.className}`,
        );
    const top = outer(parent);
    owners.add(top === null ? parent : top.parentElement);
  }
  // Every box, the outer and the inner: on one line unless it is wider than its whole line.
  for (const box of document.querySelectorAll(BOX)) {
    if (!shown(box)) continue;
    tied += 1;
    if (linesOf(box).length <= 1) continue;
    if (wide(box)) wider += 1;
    else split.push(`"${box.textContent}" (${box.className})`);
  }
  // A last line of one word, per text as the reader sees it, across its boxes. A word as the
  // reader counts it: "60 days." on a line is two words held together, in a box or not. A box
  // wider than its whole line breaks between its words or parts and may leave one alone: that
  // is allowed.
  for (const owner of owners) {
    /** Each line of the text by its top: how many words, the words or boxes on it, and their left. */
    const lines = new Map();
    let words = 0;
    const add = (top, n, unit, left, free) => {
      const line = lines.get(top) ?? { n: 0, units: [], left: Infinity, free: false };
      lines.set(top, {
        n: line.n + n,
        units: [...line.units, unit],
        left: Math.min(line.left, left),
        free: line.free || free,
      });
      words += n;
    };
    const rectOf = (node, from, to) => {
      const range = document.createRange();
      range.setStart(node, from);
      range.setEnd(node, to);
      return range.getClientRects()[0];
    };
    // With large text the headline may set a part's name on a line of its own.
    const apart = big && owner.matches('.lead');
    for (const child of owner.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        for (const word of child.data.matchAll(/[^ \n\u00a0]+/g)) {
          const rect = rectOf(child, word.index, word.index + word[0].length);
          add(Math.round(rect.top), 1, word[0], rect.left, false);
        }
        continue;
      }
      if (child.matches?.(BOX) !== true) continue;
      const inner = textsIn(child);
      if (inner.length === 0) continue;
      const free = wide(child) || (apart && child.matches('.nm'));
      if (free) {
        for (const text of inner)
          for (const word of text.data.matchAll(/[^ \n]+/g)) {
            const rect = rectOf(text, word.index, word.index + word[0].length);
            add(Math.round(rect.top), 1, word[0], rect.left, true);
          }
        continue;
      }
      const rect = rectOf(inner[0], 0, inner[0].data.length);
      add(
        Math.round(rect.top),
        child.textContent.split(/[ \n]+/).filter(Boolean).length,
        child.textContent,
        rect.left,
        false,
      );
    }
    const counts = [...lines.entries()].sort((a, b) => a[0] - b[0]).map(([, line]) => line);
    // With large text a text of two words that cannot share a line has a word on each.
    if (big && words <= 2) continue;
    const last = counts[counts.length - 1];
    if (counts.length < 2 || last.n !== 1 || last.free) continue;
    // A word alone that could not have company: the last word or box of the line above and it,
    // set on one line, are wider than the text's lines can be. No wrapping can avoid that.
    const probe = document.createElement('span');
    probe.style.cssText =
      'position:absolute;visibility:hidden;white-space:nowrap;inline-size:max-content';
    probe.textContent = `${counts[counts.length - 2].units.at(-1)} ${last.units[0]}`;
    owner.append(probe);
    const both = probe.getBoundingClientRect().width;
    probe.remove();
    const style = getComputedStyle(owner);
    const right =
      owner.getBoundingClientRect().right -
      parseFloat(style.paddingRight) -
      parseFloat(style.borderRightWidth);
    const room = right - Math.min(...counts.map((line) => line.left));
    if (both > room + 0.5) {
      alone += 1;
      continue;
    }
    lone.push(`"${owner.textContent}" (${owner.className || owner.tagName.toLowerCase()})`);
  }
  // No element reaches past the sides of the element it is in.
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('svg') !== null && el.tagName.toLowerCase() !== 'svg') continue;
    if (el.parentElement === null || !shown(el)) continue;
    const rect = el.getBoundingClientRect();
    const box = el.parentElement.getBoundingClientRect();
    if (rect.width > 0 && (rect.left < box.left - 0.5 || rect.right > box.right + 0.5))
      spill.push(
        `${el.tagName.toLowerCase()}.${el.getAttribute('class') ?? ''} "${el.textContent.trim().slice(0, 40)}" past ` +
          `${el.parentElement.tagName.toLowerCase()}.${el.parentElement.className} by ` +
          `${Math.round(Math.max(box.left - rect.left, rect.right - box.right))} px`,
      );
  }
  // The axis: half a line apart on one line, or "Today" on the next, still under the last bar.
  const half = parseFloat(getComputedStyle(document.documentElement).fontSize) / 2;
  for (const p of document.querySelectorAll('.axis')) {
    if (!shown(p)) continue;
    const [start, end] = [...p.children].map((span) => span.getBoundingClientRect());
    const bars = p.previousElementSibling.getBoundingClientRect();
    const gap = end.left - start.right;
    if (Math.round(start.top) === Math.round(end.top) && gap < half - 0.5)
      axis.push(`labels ${Math.round(gap * 10) / 10} px apart`);
    if (Math.abs(end.right - bars.right) > 1)
      axis.push(`"Today" ends ${Math.round(end.right - bars.right)} px from the last bar`);
  }
  const banner = document.querySelector('.banner');
  const reserve = parseFloat(getComputedStyle(banner).minHeight);
  const height = banner.getBoundingClientRect().height;
  const grew = height > reserve + 0.5 ? `banner ${height} px over its ${reserve} px reserve` : null;
  return {
    split,
    lone,
    spill: [...new Set(spill)],
    axis: [...new Set(axis)],
    grew,
    tied,
    texts,
    wider,
    alone,
  };
}

/** The text sizes every look is taken at: the usual size, and larger text a reader sets. */
const SIZES = [100, 150, 200];

/**
 * In a state, at each of nine widths and at text of 100%, 150% and 200%: the banner's headline
 * is the largest text of the page's answer (never smaller than the body text or its usual size,
 * always larger than the line under it); nothing scrolls sideways or reaches past its box; the
 * axis labels keep apart; the banner holds its words in its reserve; and the line checks of
 * `looked` hold. Looked at as it opens with every problem shown, and again with a bar picked
 * where there are bars to pick.
 */
async function looks(browser, state) {
  const found = [];
  let count = 0;
  let texts = 0;
  let wider = 0;
  let alone = 0;
  const usual = new Map();
  for (const size of SIZES) {
    for (const width of WIDTHS) {
      // The larger text is set by a style of the test's own, which the page's policy would refuse.
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        timezoneId: 'America/New_York',
        locale: 'en-US',
        bypassCSP: true,
      });
      const page = await context.newPage();
      await (await context.request.get(`${ORIGIN}/__set?state=${state}`)).text();
      await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
      if (size !== 100) await page.addStyleTag({ content: `html { font-size: ${size}%; }` });
      await page.waitForFunction(
        () => !document.querySelector('.lead')?.textContent?.includes('Checking'),
      );
      await page.waitForTimeout(50);
      const sizes = await page.evaluate(() => {
        const px = (box) => (box === null ? null : parseFloat(getComputedStyle(box).fontSize));
        const leads = [...document.querySelectorAll('.lead')].filter(
          (box) =>
            box.getClientRects().length > 0 && getComputedStyle(box).visibility === 'visible',
        );
        return {
          body: px(document.body),
          leads: leads.map(px),
          more: px(document.querySelector('.more')),
          others: [...document.querySelectorAll('.name, .state, h2')].map(px),
          scroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      });
      if (width === 320 && size === 200 && (state === 'history' || state === 'worst'))
        await page.screenshot({
          path: join(out, `big-text-200-${state}-320.png`),
          fullPage: true,
        });
      if ((await page.locator('#more').count()) > 0) await page.locator('#more').click();
      if (width === 768 && size === 150 && (state === 'history' || state === 'stale'))
        await page.screenshot({
          path: join(out, `big-text-150-${state}-768.png`),
          fullPage: true,
        });
      const seen = [await page.evaluate(looked, { whole: WHOLE, big: size !== 100 })];
      const bars = page.locator('.bars[data-part="closings"]:not([aria-hidden="true"])');
      if ((await bars.count()) > 0) {
        await bars.scrollIntoViewIfNeeded();
        const box = await bars.boundingBox();
        await page.mouse.move(box.x + (box.width * 79.5) / 90, box.y + box.height / 2);
        await page.waitForFunction(() => document.querySelector('.note:not(.hint)') !== null);
        seen.push(await page.evaluate(looked, { whole: WHOLE, big: size !== 100 }));
      }
      await context.close();
      count += 1;
      const at = `${width} px at ${size}%`;
      if (sizes.leads.length === 0) found.push(`${at}: no headline`);
      else {
        const lead = Math.min(...sizes.leads);
        if (size === 100) usual.set(width, lead);
        if (lead < sizes.body)
          found.push(`${at}: headline ${lead} px under the body's ${sizes.body}`);
        if (sizes.more !== null && lead <= sizes.more)
          found.push(`${at}: headline ${lead} px not over the line under it (${sizes.more})`);
        const bigger = sizes.others.filter((other) => other > lead);
        if (bigger.length > 0) found.push(`${at}: headline ${lead} px under ${bigger.join(', ')}`);
        if (lead < (usual.get(width) ?? 0))
          found.push(`${at}: headline ${lead} px under its usual ${usual.get(width)}`);
      }
      if (sizes.scroll > 0) found.push(`${at}: scrolls sideways ${sizes.scroll} px`);
      if (seen.every((one) => one.tied === 0)) found.push(`${at}: nothing tied was found`);
      for (const one of seen) {
        texts += one.texts;
        wider += one.wider;
        alone += one.alone;
        for (const text of one.split) found.push(`${at}: split ${text}`);
        for (const text of one.lone) found.push(`${at}: a last line of one word in ${text}`);
        for (const text of one.spill) found.push(`${at}: ${text}`);
        for (const text of one.axis) found.push(`${at}: axis ${text}`);
        if (one.grew !== null) found.push(`${at}: ${one.grew}`);
      }
    }
  }
  return said(
    found.length === 0,
    `looks ${state}`,
    found.length === 0
      ? `${count} looks at ${WIDTHS.join(', ')} px and ${SIZES.join('%, ')}% (${texts} texts): ` +
          'the headline is never under the body, the names, the states or the headings, always ' +
          'over the line under it and never under its usual size; nothing scrolls sideways or ' +
          'reaches past its box; the axis labels keep apart; the banner holds its words; no ' +
          `name, date, time, length or count split (${wider} boxes wider than their line broke ` +
          `between their parts) and no one-word last line that wrapping could avoid (${alone} ` +
          'words alone whose line above could not take them)'
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
      seen.states.every((state) => state.replace(/\u00a0/g, ' ') === 'Could not check'),
    'coming back to the tab',
    `"${seen.before}" became "${seen.shown}" in the same task as pageshow, rows: ${[...new Set(seen.states)].join(', ')}`,
  );
}

/**
 * The banner's reserve holds its longest copy (every part named and "Could not refresh. This is
 * the check from 14 minutes ago.") at every 2 px of room from 8rem to 43rem, so nothing moves
 * when it fills, whatever the screen and the text size.
 */
async function reserves(browser) {
  const context = await browser.newContext({
    viewport: { width: 400, height: 900 },
    timezoneId: 'America/New_York',
    locale: 'en-US',
  });
  await (await context.request.get(`${ORIGIN}/__set?state=worst`)).text();
  const page = await context.newPage();
  const found = [];
  let most = 0;
  let count = 0;
  for (let width = 160; width <= 720; width += 2) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${ORIGIN}/`, { waitUntil: 'load' });
    await page.waitForFunction(
      () => !document.querySelector('.lead')?.textContent?.includes('Checking'),
    );
    const seen = await page.evaluate(() => {
      const banner = document.querySelector('.banner');
      const reserve = parseFloat(getComputedStyle(banner).minHeight);
      banner.style.minHeight = '0';
      document.querySelector('.more').textContent =
        'Could not refresh. This is the check from 14\u00a0minutes\u00a0ago.';
      const need = banner.getBoundingClientRect().height;
      return { reserve, need };
    });
    count += 1;
    most = Math.max(most, seen.reserve - seen.need);
    if (seen.need > seen.reserve + 0.5)
      found.push(`${(width - 32) / 16}rem: needs ${seen.need} px of its ${seen.reserve} px`);
  }
  await context.close();
  return said(
    found.length === 0,
    'banner reserve',
    found.length === 0
      ? `the longest copy fits at all ${count} widths of room from 8rem to 43rem, with at most ` +
          `${most} px to spare`
      : found.join('; '),
  );
}

/** Text at 150% on a 320 px screen: every box wraps, nothing scrolls sideways, no line splits. */
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
  if ((await page.locator('#more').count()) > 0) await page.locator('#more').click();
  const lines = await page.evaluate(looked, { whole: WHOLE, big: true });
  await page.screenshot({ path: join(out, `big-text-${state}-320.png`), fullPage: true });
  await context.close();
  const words = [
    ...lines.split.map((text) => `split ${text}`),
    ...lines.lone.map((text) => `a last line of one word in ${text}`),
  ];
  return said(
    seen.scroll <= 0 && seen.wide.length === 0 && words.length === 0,
    `big-text-${state}-320`,
    `horizontal scroll ${Math.max(0, seen.scroll)} px` +
      (seen.wide.length === 0
        ? ', no box past the edge'
        : `; past the edge: ${seen.wide.join(' ')}`) +
      (words.length === 0
        ? `; ${lines.texts} texts, none split and no one-word last line`
        : `; ${words.join('; ')}`),
  );
}

module.exports = { looks, looked, wholeRuns, setWhole: (runs) => (WHOLE = runs) };

if (require.main === module)
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });

async function main() {
  mkdirSync(out, { recursive: true });
  WHOLE = await wholeRuns();
  const browser = await chromium.launch();
  let good = true;
  for (const shot of SHOTS) good = (await one(browser, shot)) && good;
  good = (await scriptsOff(browser)) && good;
  good = (await scriptMissing(browser)) && good;
  good = (await comingBack(browser)) && good;
  good = (await reserves(browser)) && good;
  for (const state of ['history', 'worst', 'stale', 'first', 'unreachable'])
    good = (await bigText(browser, state)) && good;
  for (const state of ['history', 'worst', 'launch', 'ok', 'stale', 'first', 'unreachable'])
    good = (await looks(browser, state)) && good;
  await browser.close();
  process.exit(good ? 0 : 1);
}

// Finalsite page check: open each district homepage in Chromium and record the page pops it asks for.
//
//   uv run python -m snowlight.sources.stations.finalsite_check targets > targets.json
//   node pipeline/snowlight/sources/stations/finalsite_pagecheck.cjs targets.json OUT_DIR [ID ...]
//   uv run python -m snowlight.sources.stations.finalsite_check apply OUT_DIR [--write]
//
// For every target ({"id", "urls", "user_agent"}) each URL is opened once in headless
// Chromium with the project's own User-Agent (never a browser string); images, media and
// fonts are not loaded. The page is given up to 20 s to ask for its page pops
// (/fs/pages/<id>/page-pops, the address Finalsite's script builds from the page's
// body data-pageid), and 3 s more once it has. Recorded per page: the body's
// data-pageid, every page-pops request with its answer (status, bytes, SHA-256, the
// body saved under OUT_DIR/bodies/<sha256>), and how many page pops the page then
// holds. One JSON file per station goes to OUT_DIR/pages/<id>.json. Only the homepage
// itself is opened (never a crawl); a page that answers with a block or a challenge is
// recorded as it is and never worked around.
//
// Playwright is the web app's dev dependency (web/node_modules/playwright); set
// PLAYWRIGHT_MODULE and CHROMIUM_PATH to use another install.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const moduleDir =
  process.env.PLAYWRIGHT_MODULE ||
  path.resolve(__dirname, '../../../../web/node_modules/playwright');
const { chromium } = require(moduleDir);

const PAGE_POPS = /\/fs\/pages\/[^/?#]+\/page-pops(?:[?#]|$)/;
const WORKERS = 2;
const PATIENCE_MS = 20000;
const AFTER_MS = 3000;

async function check(context, target, url, out) {
  const page = await context.newPage();
  const requests = [];
  const responses = [];
  const saves = [];
  page.on('request', (request) => {
    if (PAGE_POPS.test(request.url())) {
      requests.push({ url: request.url(), type: request.resourceType() });
    }
  });
  page.on('response', (response) => {
    const address = response.url();
    if (!PAGE_POPS.test(address)) return;
    const headers = response.headers();
    const record = {
      url: address,
      status: response.status(),
      type: response.request().resourceType(),
      content_type: headers['content-type'] || null,
    };
    responses.push(record);
    saves.push(
      response
        .body()
        .then((body) => {
          const sha = crypto.createHash('sha256').update(body).digest('hex');
          record.sha256 = sha;
          record.bytes = body.length;
          fs.writeFileSync(path.join(out, 'bodies', sha), body);
        })
        .catch((error) => {
          record.body_error = String(error).slice(0, 200);
        }),
    );
  });
  const started = new Date().toISOString();
  let error = null;
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const deadline = Date.now() + PATIENCE_MS;
    while (Date.now() < deadline && responses.length === 0) {
      await page.waitForTimeout(500);
    }
    await page.waitForTimeout(AFTER_MS);
  } catch (caught) {
    error = String(caught).slice(0, 300);
  }
  let pageid = null;
  let pops = null;
  let title = null;
  try {
    [pageid, pops, title] = await page.evaluate(() => [
      document.body ? document.body.getAttribute('data-pageid') : null,
      document.querySelectorAll('article.fsPagePop').length,
      document.title,
    ]);
  } catch (caught) {
    error = error || String(caught).slice(0, 300);
  }
  const finalUrl = page.url();
  await Promise.all(saves);
  await page.close();
  return {
    id: target.id,
    url,
    final_url: finalUrl,
    started,
    ended: new Date().toISOString(),
    error,
    title,
    body_pageid: pageid,
    pops_in_page: pops,
    requests,
    responses,
  };
}

async function main() {
  const [targetsFile, out, ...only] = process.argv.slice(2);
  if (!targetsFile || !out) {
    console.error('usage: finalsite_pagecheck.cjs TARGETS.json OUT_DIR [ID ...]');
    process.exit(2);
  }
  const targets = JSON.parse(fs.readFileSync(targetsFile, 'utf8'));
  fs.mkdirSync(path.join(out, 'pages'), { recursive: true });
  fs.mkdirSync(path.join(out, 'bodies'), { recursive: true });
  const queue = targets.filter((t) => t.urls.length && (only.length === 0 || only.includes(t.id)));
  const agents = new Set(queue.map((t) => t.user_agent));
  if (agents.size !== 1) throw new Error('every target names the same User-Agent');
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ['--no-sandbox'],
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1800 },
    userAgent: [...agents][0],
  });
  await context.route('**/*', (route) =>
    ['image', 'media', 'font'].includes(route.request().resourceType())
      ? route.abort()
      : route.continue(),
  );
  async function worker() {
    while (queue.length) {
      const target = queue.shift();
      const pages = [];
      for (const url of target.urls) {
        pages.push(await check(context, target, url, out));
      }
      fs.writeFileSync(
        path.join(out, 'pages', `${target.id}.json`),
        JSON.stringify({ id: target.id, pages }, null, 1),
      );
      console.log(`${target.id}: ${pages.map((p) => p.error || p.body_pageid).join(', ')}`);
    }
  }
  await Promise.all(Array.from({ length: WORKERS }, worker));
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

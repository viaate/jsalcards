// Page check: open each station's closings page in Chromium and record what it loads.
//
//   uv run snowlight stations pagecheck targets > targets.json
//   node pipeline/snowlight/sources/stations/pagecheck.cjs targets.json OUT_DIR [ID ...]
//   uv run snowlight stations pagecheck apply OUT_DIR [--write]
//
// For every target ({"id", "urls", "user_agent"}) each URL is opened once in headless
// Chromium with the project's own User-Agent (never a browser string); images, media
// and fonts are not loaded. The page is given 12 s, scrolled to its end, and given 5 s
// more. Every request and response is recorded, with the body of each closings-like
// document, script or data response (saved under OUT_DIR/bodies/<sha256>), and the
// text every frame shows. One JSON file per station goes to OUT_DIR/pages/<id>.json.
// Only the closings page itself is opened (never a crawl); a page that answers with a
// block or a challenge is recorded as it is and never worked around.
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

const RELEVANT =
  /closing|gsync|grayfilestore|webpubcontent|amb-feeds|ftp2\.|flashalert|schoolclos|delays|\.xml(\?|$)|content\/fetch/i;
const STATIC = /\.(css|png|jpe?g|gif|svg|webp|woff2?|ttf|ico|mp4)(\?|$)/i;
const WORKERS = 2;

async function check(context, target, url, out) {
  const page = await context.newPage();
  const requests = [];
  const responses = [];
  const saves = [];
  page.on('request', (request) => {
    const address = request.url();
    if (!STATIC.test(address) && RELEVANT.test(address)) {
      requests.push({ url: address, type: request.resourceType() });
    }
  });
  page.on('response', (response) => {
    const address = response.url();
    const type = response.request().resourceType();
    if (STATIC.test(address) || !RELEVANT.test(address)) return;
    const headers = response.headers();
    const record = {
      url: address,
      status: response.status(),
      type,
      content_type: headers['content-type'] || null,
      last_modified: headers['last-modified'] || null,
      date: headers.date || null,
      etag: headers.etag || null,
    };
    responses.push(record);
    if (['document', 'xhr', 'fetch', 'script'].includes(type) && response.status() === 200) {
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
    }
  });
  const started = new Date().toISOString();
  let error = null;
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(12000);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)).catch(() => {});
    await page.waitForTimeout(5000);
  } catch (caught) {
    error = String(caught).slice(0, 300);
  }
  const frames = [];
  for (const frame of page.frames()) {
    let text;
    try {
      text = await frame.evaluate(() => (document.body ? document.body.innerText : ''));
    } catch (caught) {
      text = 'ERR ' + String(caught).slice(0, 100);
    }
    frames.push({ url: frame.url(), text: (text || '').slice(0, 4000) });
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
    requests,
    responses,
    frames,
  };
}

async function main() {
  const [targetsFile, out, ...only] = process.argv.slice(2);
  if (!targetsFile || !out) {
    console.error('usage: pagecheck.cjs TARGETS.json OUT_DIR [ID ...]');
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
        pages.push(await check(context, target, url, out).catch((e) => ({ id: target.id, url, error: String(e) })));
      }
      fs.writeFileSync(path.join(out, 'pages', `${target.id}.json`), JSON.stringify(pages, null, 1));
      console.log(target.id, pages.map((p) => (p.error ? 'error' : 'ok')).join(' '));
    }
  }
  await Promise.all(Array.from({ length: WORKERS }, worker));
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

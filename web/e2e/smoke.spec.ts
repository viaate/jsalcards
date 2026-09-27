import { expect, test } from '@playwright/test';

/** Chromium's own GPU driver chatter under software WebGL, not the page's. */
const GPU_DRIVER_NOISE =
  /GL Driver Message|GPU stall due to ReadPixels|Automatic fallback to software WebGL/;

test('loads on a black, full-viewport ground with no console errors', async ({ page, baseURL }) => {
  const problems: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'warning' && GPU_DRIVER_NOISE.test(message.text())) return;
    if (message.type() === 'error' || message.type() === 'warning') {
      problems.push(`console.${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('requestfailed', (request) => problems.push(`requestfailed: ${request.url()}`));
  page.on('response', (response) => {
    if (response.status() >= 400)
      problems.push(`HTTP ${String(response.status())}: ${response.url()}`);
  });
  const foreign: string[] = [];
  page.on('request', (request) => {
    if (baseURL !== undefined && new URL(request.url()).origin !== new URL(baseURL).origin) {
      foreign.push(request.url());
    }
  });

  await page.goto('/', { waitUntil: 'networkidle' });

  await expect(page).toHaveTitle('Snowlight');
  await expect(page.locator('main')).toBeAttached();

  const colors = await page.evaluate(() => {
    const background = (selector: string): string => {
      const element = document.querySelector(selector);
      return element === null ? 'missing' : getComputedStyle(element).backgroundColor;
    };
    return { html: background('html'), body: background('body'), main: background('main') };
  });
  expect(colors).toEqual({ html: 'rgb(0, 0, 0)', body: 'rgb(0, 0, 0)', main: 'rgb(0, 0, 0)' });

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  const box = await page.locator('main').boundingBox();
  expect(box).toEqual({ x: 0, y: 0, width: viewport?.width, height: viewport?.height });

  // The ground and the country are both pure black: only the map's hairlines,
  // its city names and the chrome are lit, so nearly every pixel on screen is
  // #000 or within a step of it.
  const shot = await page.screenshot({ type: 'png' });
  const shares = await page.evaluate(async (base64) => {
    const bitmap = await createImageBitmap(
      await (await fetch(`data:image/png;base64,${base64}`)).blob(),
    );
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext('2d');
    if (context === null) return { dark: 0, black: 0 };
    context.drawImage(bitmap, 0, 0);
    const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height);
    let dark = 0;
    let black = 0;
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i] ?? 255;
      const g = data[i + 1] ?? 255;
      const b = data[i + 2] ?? 255;
      if (r === g && g === b && r <= 10) dark += 1;
      if (r === 0 && g === 0 && b === 0) black += 1;
    }
    return { dark: dark / (data.length / 4), black: black / (data.length / 4) };
  }, shot.toString('base64'));
  expect(shares.dark).toBeGreaterThan(0.8);
  expect(shares.black).toBeGreaterThan(0.2);

  expect(problems).toEqual([]);
  expect(foreign).toEqual([]);
});

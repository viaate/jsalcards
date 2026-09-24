import { expect, test } from '@playwright/test';

test('loads a black, full-viewport page with no console errors', async ({ page, baseURL }) => {
  const problems: string[] = [];
  page.on('console', (message) => {
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

  // Every pixel on screen is pure black.
  const shot = await page.screenshot({ type: 'png' });
  const allBlack = await page.evaluate(async (base64) => {
    const bitmap = await createImageBitmap(
      await (await fetch(`data:image/png;base64,${base64}`)).blob(),
    );
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext('2d');
    if (context === null) return false;
    context.drawImage(bitmap, 0, 0);
    const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height);
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] !== 0 || data[i + 1] !== 0 || data[i + 2] !== 0) return false;
    }
    return true;
  }, shot.toString('base64'));
  expect(allBlack).toBe(true);

  expect(problems).toEqual([]);
  expect(foreign).toEqual([]);
});

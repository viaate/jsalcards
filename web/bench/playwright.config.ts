import { resolve } from 'node:path';

import { defineConfig } from '@playwright/test';

/**
 * Runs e2e/bench-glow.spec.ts against a production build of the bench page.
 * `npm run bench:glow` uses this config; the app's own e2e run skips the bench.
 *
 * There is no GPU here: Chromium renders WebGL2 with SwiftShader on the CPU,
 * so frame rates measure the software rasterizer, not a real graphics card.
 */
const port = Number(process.env.BENCH_PORT ?? '5103');
// One id per run, inherited by workers, so the spec starts glow.json fresh each run.
process.env.GLOW_BENCH_RUN ??= new Date().toISOString();
const baseURL = `http://127.0.0.1:${String(port)}`;
const web = resolve(import.meta.dirname, '..');

export default defineConfig({
  testDir: resolve(web, 'e2e'),
  testMatch: 'bench-glow.spec.ts',
  outputDir: resolve(web, 'bench/out/test-results'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 600_000,
  reporter: 'list',
  use: {
    baseURL,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    launchOptions: {
      args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
    },
  },
  projects: [{ name: 'glow-bench', use: { browserName: 'chromium' } }],
  webServer: {
    command: `npx vite build -c bench/vite.config.ts --logLevel warn && npx vite preview -c bench/vite.config.ts --host 127.0.0.1 --port ${String(port)} --strictPort`,
    cwd: web,
    url: `${baseURL}/glow.html`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});

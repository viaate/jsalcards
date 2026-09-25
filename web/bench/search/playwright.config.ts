import { defineConfig } from '@playwright/test';

import { benchOutDir } from './vite.config';

/**
 * Runs search.bench.ts: `npm run bench:search`. The spec builds and serves
 * its own page (port SEARCH_BENCH_PORT, default 5107), so there is no
 * webServer here. The search worker uses no WebGL, so no GPU is involved.
 */
export default defineConfig({
  testDir: import.meta.dirname,
  testMatch: 'search.bench.ts',
  outputDir: `${benchOutDir}/test-results`,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 600_000,
  reporter: 'list',
  use: {
    browserName: 'chromium',
    viewport: { width: 1440, height: 900 },
  },
});

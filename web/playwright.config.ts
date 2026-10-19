import { defineConfig, devices } from '@playwright/test';

import {
  WAITLIST_CHROME_DIST,
  WAITLIST_CHROME_PORT,
  WAITLIST_CHROME_URL,
  WAITLIST_DIST,
  WAITLIST_FORM,
  WAITLIST_PORT,
  WAITLIST_URL,
} from './e2e/waitlist-server';

// Each agent or CI job picks its own port so parallel runs never share a server.
const port = Number(process.env.E2E_PORT ?? '4173');
const baseURL = `http://127.0.0.1:${String(port)}`;
const isCI = process.env.CI !== undefined;

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: 0,
  reporter: isCI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      // Smoke-test the production build, not the dev server. It ships no data, whatever is
      // staged in public/data/; specs that need data build their own (e2e/app.spec.ts,
      // e2e/real-data.spec.ts).
      command: `SNOWLIGHT_DATA=none npm run build && npm run preview -- --host 127.0.0.1 --port ${String(port)} --strictPort`,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The same site built with the waitlist on (tools/waitlist.ts), for e2e/waitlist.spec.ts.
      command: `VITE_WAITLIST_KIT_FORM=${WAITLIST_FORM} SNOWLIGHT_DATA=none npx vite build --outDir ${WAITLIST_DIST} --emptyOutDir && npx vite preview --outDir ${WAITLIST_DIST} --host 127.0.0.1 --port ${String(WAITLIST_PORT)} --strictPort`,
      url: WAITLIST_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The waitlist with its headline in the wordmark's chrome lettering (VITE_WAITLIST_HEADLINE=chrome).
      command: `VITE_WAITLIST_KIT_FORM=${WAITLIST_FORM} VITE_WAITLIST_HEADLINE=chrome SNOWLIGHT_DATA=none npx vite build --outDir ${WAITLIST_CHROME_DIST} --emptyOutDir && npx vite preview --outDir ${WAITLIST_CHROME_DIST} --host 127.0.0.1 --port ${String(WAITLIST_CHROME_PORT)} --strictPort`,
      url: WAITLIST_CHROME_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});

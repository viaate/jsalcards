import { defineConfig, devices } from '@playwright/test';

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
  webServer: {
    // Smoke-test the production build, not the dev server. It ships no data, whatever is
    // staged in public/data/; specs that need data build their own (e2e/app.spec.ts,
    // e2e/real-data.spec.ts).
    command: `SNOWLIGHT_DATA=none npm run build && npm run preview -- --host 127.0.0.1 --port ${String(port)} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});

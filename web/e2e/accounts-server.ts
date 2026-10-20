/**
 * The accounts build the e2e tests serve beside the usual one
 * (playwright.config.ts): built with a made-up API root, whose every request
 * the tests answer themselves (e2e/accounts.spec.ts), so nothing leaves the
 * machine.
 */
const port = Number(process.env.E2E_PORT ?? '4173');

export const ACCOUNTS_API = 'https://api.snowlight.test';
export const ACCOUNTS_PORT = Number(process.env.E2E_ACCOUNTS_PORT ?? String(port + 3));
export const ACCOUNTS_URL = `http://127.0.0.1:${String(ACCOUNTS_PORT)}`;
export const ACCOUNTS_DIST = 'dist-accounts';

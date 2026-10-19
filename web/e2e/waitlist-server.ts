/**
 * The waitlist build the e2e tests serve beside the usual one
 * (playwright.config.ts): built with a made-up Kit form id, whose endpoint
 * every test answers itself, so no signup ever leaves the machine.
 */
const port = Number(process.env.E2E_PORT ?? '4173');

export const WAITLIST_FORM = '1234567';
export const WAITLIST_PORT = Number(process.env.E2E_WAITLIST_PORT ?? String(port + 1));
export const WAITLIST_URL = `http://127.0.0.1:${String(WAITLIST_PORT)}`;
export const WAITLIST_DIST = 'dist-waitlist';

/** The same waitlist with its headline in chrome (VITE_WAITLIST_HEADLINE=chrome). */
export const WAITLIST_CHROME_PORT = Number(
  process.env.E2E_WAITLIST_CHROME_PORT ?? String(port + 2),
);
export const WAITLIST_CHROME_URL = `http://127.0.0.1:${String(WAITLIST_CHROME_PORT)}`;
export const WAITLIST_CHROME_DIST = 'dist-waitlist-chrome';

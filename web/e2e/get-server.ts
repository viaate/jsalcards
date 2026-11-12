/**
 * The getsnowlight landing the e2e tests serve beside the map (playwright.config.ts), built on
 * its own as the workflow builds it (vite.get.config.ts, docs/getsnowlight.md).
 */
const port = Number(process.env.E2E_PORT ?? '4173');

export const GET_PORT = Number(process.env.E2E_GET_PORT ?? String(port + 4));
export const GET_URL = `http://127.0.0.1:${String(GET_PORT)}`;

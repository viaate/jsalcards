#!/usr/bin/env node
/**
 * Performance gate for the app shell: "npm run perf".
 *
 * Builds the site, serves it with vite preview, and runs Lighthouse against it:
 * the mobile preset (simulated slow 4G, 4x CPU) and the desktop preset, three
 * runs each, plus one mobile run with applied (devtools) 4G throttling. Medians
 * go to perf/lighthouse.json and full reports to perf/raw/ (not committed).
 *
 * Gate: Performance, Accessibility, Best Practices and SEO at 90 or more in
 * both presets; mobile FCP under 1.5 s; CLS 0 in every run; nothing logged to
 * the console as an error; no request leaves the site at the initial view;
 * FCP under 1.5 s with applied throttling too; MapLibre's scripts at or under
 * 310 KB gzipped, with one copy of its shared module among every script loaded.
 *
 * Environment: PERF_PORT (default 5104), CHROME_PATH (default: the
 * preinstalled Playwright Chromium), PERF_RUNS (default 3), and --skip-build
 * to reuse dist/.
 *
 * WebGL runs wherever Chrome can run it. On a machine without a GPU that is
 * SwiftShader, a software renderer, which makes every map frame much slower
 * than on real hardware; the report records which renderer was used.
 */
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import { dirname, join } from 'node:path';
import process from 'node:process';
import { clearTimeout, setTimeout } from 'node:timers';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

import { chromium } from '@playwright/test';
import lighthouse from 'lighthouse';
import desktopConfig from 'lighthouse/core/config/desktop-config.js';
import prettier from 'prettier';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(WEB, 'dist');
const RAW_DIR = join(WEB, 'perf/raw');
const REPORT = join(WEB, 'perf/lighthouse.json');
const PORT = Number(process.env.PERF_PORT ?? '5104');
const RUNS = Number(process.env.PERF_RUNS ?? '3');
const ORIGIN = `http://127.0.0.1:${String(PORT)}`;
const URL_UNDER_TEST = `${ORIGIN}/`;
const DEFAULT_CHROME = '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const CHROME_PATH = process.env.CHROME_PATH ?? DEFAULT_CHROME;

const CATEGORIES = ['performance', 'accessibility', 'best-practices', 'seo'];
const MIN_SCORE = 0.9;
const MAX_FCP_MS = 1500;
/** MapLibre's scripts, which load after first paint, gzipped at zlib's default level. */
const MAX_MAPLIBRE_GZIP_BYTES = 310_000;
/** A name only MapLibre's shared module defines: each file containing it is a copy. */
const SHARED_MODULE_MARKER = 'REGISTERED_PROTOCOLS';

const CHROME_FLAGS = process.env.PERF_CHROME_FLAGS?.split(' ') ?? [
  '--headless=new',
  '--no-sandbox',
  '--no-first-run',
  '--disable-extensions',
  // Chrome only runs WebGL on SwiftShader when asked to; without it the map would not render at all.
  '--enable-unsafe-swiftshader',
];

/**
 * Flags that keep Chrome's own background work out of the measurement, the
 * ones Lighthouse's launcher passes by default.
 */
const QUIET_CHROME_FLAGS = [
  '--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater,AutofillServerCommunication,PrivacySandboxSettings4,RenderDocument',
  '--disable-component-extensions-with-background-pages',
  '--disable-background-networking',
  '--disable-component-update',
  '--disable-client-side-phishing-detection',
  '--disable-sync',
  '--metrics-recording-only',
  '--disable-default-apps',
  '--mute-audio',
  '--no-default-browser-check',
  '--disable-backgrounding-occluded-windows',
  '--disable-renderer-backgrounding',
  '--disable-background-timer-throttling',
  '--disable-ipc-flooding-protection',
  '--password-store=basic',
  '--use-mock-keychain',
  '--disable-hang-monitor',
  '--disable-prompt-on-repost',
  '--disable-domain-reliability',
];

/** @param {number[]} values */
function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? (sorted[middle] ?? NaN)
    : ((sorted[middle - 1] ?? NaN) + (sorted[middle] ?? NaN)) / 2;
}

/** @param {string} command @param {string[]} args */
function run(command, args) {
  const result = spawnSync(command, args, { cwd: WEB, stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} ${args.join(' ')} failed`);
}

async function startPreview() {
  const vite = join(WEB, 'node_modules/vite/bin/vite.js');
  const server = spawn(
    process.execPath,
    [vite, 'preview', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'],
    { cwd: WEB, stdio: ['ignore', 'pipe', 'pipe'] },
  );
  let output = '';
  server.stdout.on('data', (chunk) => (output += String(chunk)));
  server.stderr.on('data', (chunk) => (output += String(chunk)));
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`vite preview exited:\n${output}`);
    try {
      const response = await globalThis.fetch(URL_UNDER_TEST);
      if (response.ok) return server;
    } catch {
      // Not listening yet.
    }
    await sleep(200);
  }
  server.kill();
  throw new Error(`vite preview did not start on ${ORIGIN}:\n${output}`);
}

/**
 * Starts Chrome with a fresh profile and remote debugging on a free port, for
 * Lighthouse to drive. Chrome prints the port it chose on stderr.
 */
async function launchChrome() {
  const profile = await mkdtemp(join(os.tmpdir(), 'snowlight-perf-'));
  const chrome = spawn(
    CHROME_PATH,
    [
      ...CHROME_FLAGS,
      ...QUIET_CHROME_FLAGS,
      '--remote-debugging-port=0',
      `--user-data-dir=${profile}`,
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] },
  );
  const exited = new Promise((resolve) => chrome.once('exit', resolve));
  const kill = async () => {
    if (chrome.exitCode === null && chrome.signalCode === null) {
      chrome.kill();
      await exited;
    }
    await rm(profile, { recursive: true, force: true });
  };
  try {
    /** @type {number} */
    const port = await new Promise((resolve, reject) => {
      let stderr = '';
      const timer = setTimeout(() => {
        reject(new Error(`Chrome did not open a debugging port:\n${stderr}`));
      }, 30_000);
      chrome.stderr.on('data', (chunk) => {
        stderr += String(chunk);
        const match = /DevTools listening on ws:\/\/[^:]+:(\d+)\//.exec(stderr);
        if (match !== null) {
          clearTimeout(timer);
          resolve(Number(match[1]));
        }
      });
      chrome.once('exit', (code) => {
        clearTimeout(timer);
        reject(new Error(`Chrome exited (${String(code)}) before it was ready:\n${stderr}`));
      });
    });
    return { port, kill };
  } catch (error) {
    await kill();
    throw error;
  }
}

/**
 * @param {import('lighthouse').Config | undefined} config
 * @param {Record<string, unknown>} settings
 */
async function audit(config, settings) {
  const chrome = await launchChrome();
  try {
    const result = await lighthouse(
      URL_UNDER_TEST,
      { port: chrome.port, output: 'json', logLevel: 'error', ...settings },
      config,
    );
    if (result === undefined) throw new Error('Lighthouse returned no result');
    return result.lhr;
  } finally {
    await chrome.kill();
  }
}

/** @param {import('lighthouse').Result} lhr */
function summarize(lhr) {
  /** @param {string} id */
  const numeric = (id) => lhr.audits[id]?.numericValue ?? NaN;
  /** @type {Record<string, number>} */
  const scores = {};
  for (const id of CATEGORIES) scores[id] = Math.round((lhr.categories[id]?.score ?? 0) * 100);

  const consoleAudit = lhr.audits['errors-in-console'];
  const consoleItems =
    /** @type {{ items?: Array<{ description?: string, source?: string }> } | undefined} */ (
      consoleAudit?.details
    )?.items ?? [];
  const requests =
    /** @type {{ items?: Array<{ url?: string }> } | undefined} */ (
      lhr.audits['network-requests']?.details
    )?.items ?? [];
  // Blob URLs the page made itself (MapLibre's workers start from one) carry the site's origin.
  const foreign = requests
    .map((item) => item.url ?? '')
    .filter(
      (url) =>
        url !== '' &&
        !url.startsWith(`${ORIGIN}/`) &&
        !url.startsWith(`blob:${ORIGIN}/`) &&
        !url.startsWith('data:'),
    );
  const scripts = [
    ...new Set(
      requests
        .map((item) => item.url ?? '')
        .filter((url) => url.startsWith(`${ORIGIN}/assets/`) && url.endsWith('.js'))
        .map((url) => url.slice(ORIGIN.length + 1)),
    ),
  ].sort();

  return {
    scores,
    fcpMs: Math.round(numeric('first-contentful-paint')),
    lcpMs: Math.round(numeric('largest-contentful-paint')),
    speedIndexMs: Math.round(numeric('speed-index')),
    tbtMs: Math.round(numeric('total-blocking-time')),
    cls: numeric('cumulative-layout-shift'),
    consoleErrors: consoleItems.map((item) => item.description ?? item.source ?? 'error'),
    foreignRequests: foreign,
    requests: requests.length,
    scripts,
    benchmarkIndex: lhr.environment.benchmarkIndex,
    warnings: lhr.runWarnings,
  };
}

/** @param {ReturnType<typeof summarize>[]} runs */
function medians(runs) {
  /** @type {Record<string, number>} */
  const scores = {};
  for (const id of CATEGORIES) scores[id] = median(runs.map((r) => r.scores[id] ?? 0));
  return {
    scores,
    fcpMs: median(runs.map((r) => r.fcpMs)),
    lcpMs: median(runs.map((r) => r.lcpMs)),
    speedIndexMs: median(runs.map((r) => r.speedIndexMs)),
    tbtMs: median(runs.map((r) => r.tbtMs)),
    cls: median(runs.map((r) => r.cls)),
  };
}

async function lighthouseVersion() {
  /** @type {unknown} */
  const parsed = JSON.parse(
    await readFile(join(WEB, 'node_modules/lighthouse/package.json'), 'utf8'),
  );
  return /** @type {{ version: string }} */ (parsed).version;
}

/** Runs in the page (the scripts' tsconfig has no DOM types, hence a string). */
const RENDERER_SCRIPT = `(() => {
  const gl = document.createElement('canvas').getContext('webgl2');
  if (gl === null) return 'no WebGL2';
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  return String(gl.getParameter(info === null ? gl.RENDERER : info.UNMASKED_RENDERER_WEBGL));
})()`;

/**
 * The WebGL renderer this Chrome uses with these flags, e.g. SwiftShader when
 * the machine has no GPU. Recorded so frame costs can be read in context.
 */
async function webglRenderer() {
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    args: CHROME_FLAGS.filter((flag) => flag !== '--headless=new'),
  });
  try {
    const page = await browser.newPage();
    /** @type {unknown} */
    const renderer = await page.evaluate(RENDERER_SCRIPT);
    return String(renderer);
  } finally {
    await browser.close();
  }
}

function chromeVersion() {
  const result = spawnSync(CHROME_PATH, ['--version'], { encoding: 'utf8' });
  return result.status === 0 ? result.stdout.trim() : 'unknown';
}

/**
 * The scripts loaded after first paint, read from dist/: every script
 * requested except the one index.html names. Sizes are gzipped at zlib's
 * default level, as a static host serves them.
 * @param {string[]} scripts paths under the site root, e.g. assets/basemap-XXXX.js
 */
async function lazyScripts(scripts) {
  const html = await readFile(join(DIST, 'index.html'), 'utf8');
  const entries = [...html.matchAll(/<script[^>]+src="\/([^"]+)"/g)].map((match) => match[1]);
  const files = [];
  for (const path of scripts) {
    if (entries.includes(path)) continue;
    const code = await readFile(join(DIST, path));
    files.push({
      path,
      bytes: code.length,
      gzipBytes: gzipSync(code).length,
      maplibre: path.startsWith('assets/maplibre'),
      sharedModule: code.includes(SHARED_MODULE_MARKER),
    });
  }
  const maplibre = files.filter((file) => file.maplibre);
  return {
    files,
    maplibreFiles: maplibre.length,
    maplibreGzipBytes: maplibre.reduce((sum, file) => sum + file.gzipBytes, 0),
    sharedModuleCopies: files.filter((file) => file.sharedModule).length,
  };
}

async function main() {
  if (!existsSync(CHROME_PATH)) throw new Error(`No Chrome at ${CHROME_PATH}; set CHROME_PATH`);
  if (!process.argv.includes('--skip-build')) {
    run(process.execPath, ['scripts/build-geo.mjs', '--check']);
    run('npm', ['run', 'build']);
  }
  await mkdir(RAW_DIR, { recursive: true });

  const server = await startPreview();
  /** @type {Record<string, ReturnType<typeof summarize>[]>} */
  const results = { mobile: [], desktop: [], devtools4g: [] };
  try {
    const plans = [
      ...Array.from({ length: RUNS }, () => ({
        preset: 'mobile',
        config: undefined,
        settings: {},
      })),
      ...Array.from({ length: RUNS }, () => ({
        preset: 'desktop',
        config: desktopConfig,
        settings: {},
      })),
      { preset: 'devtools4g', config: undefined, settings: { throttlingMethod: 'devtools' } },
    ];
    for (const plan of plans) {
      const runs = results[plan.preset] ?? [];
      const lhr = await audit(plan.config, plan.settings);
      await writeFile(
        join(RAW_DIR, `${plan.preset}-${String(runs.length + 1)}.json`),
        JSON.stringify(lhr),
      );
      const summary = summarize(lhr);
      runs.push(summary);
      process.stdout.write(
        `${plan.preset} #${String(runs.length)}: ${CATEGORIES.map((id) => `${id} ${String(summary.scores[id])}`).join(', ')}; ` +
          `FCP ${String(summary.fcpMs)} ms, LCP ${String(summary.lcpMs)} ms, TBT ${String(summary.tbtMs)} ms, ` +
          `SI ${String(summary.speedIndexMs)} ms, CLS ${String(summary.cls)}\n`,
      );
    }
  } finally {
    server.kill();
  }

  const mobile = medians(results.mobile ?? []);
  const desktop = medians(results.desktop ?? []);
  const devtools = results.devtools4g?.[0];
  const allRuns = Object.values(results).flat();

  /** @type {{ gate: string, value: number | string, limit: string, pass: boolean }[]} */
  const gates = [];
  for (const [preset, summary] of /** @type {const} */ ([
    ['mobile', mobile],
    ['desktop', desktop],
  ])) {
    for (const id of CATEGORIES) {
      const value = summary.scores[id] ?? 0;
      gates.push({
        gate: `${preset} ${id}`,
        value,
        limit: '>= 90',
        pass: value >= MIN_SCORE * 100,
      });
    }
  }
  gates.push({
    gate: 'mobile FCP (simulated slow 4G, median)',
    value: mobile.fcpMs,
    limit: `< ${String(MAX_FCP_MS)} ms`,
    pass: mobile.fcpMs < MAX_FCP_MS,
  });
  gates.push({
    gate: 'mobile FCP (applied devtools 4G)',
    value: devtools?.fcpMs ?? NaN,
    limit: `< ${String(MAX_FCP_MS)} ms`,
    pass: devtools !== undefined && devtools.fcpMs < MAX_FCP_MS,
  });
  const worstCls = Math.max(...allRuns.map((r) => r.cls));
  gates.push({ gate: 'CLS, every run', value: worstCls, limit: '0', pass: worstCls === 0 });
  const consoleErrors = allRuns.flatMap((r) => r.consoleErrors);
  gates.push({
    gate: 'console errors, every run',
    value: consoleErrors.length,
    limit: '0',
    pass: consoleErrors.length === 0,
  });
  const foreign = [...new Set(allRuns.flatMap((r) => r.foreignRequests))];
  gates.push({
    gate: 'requests leaving the site at the initial view',
    value: foreign.length,
    limit: '0',
    pass: foreign.length === 0,
  });
  const lazy = await lazyScripts([...new Set(allRuns.flatMap((r) => r.scripts))]);
  gates.push({
    gate: "MapLibre's scripts, gzipped",
    value: lazy.maplibreGzipBytes,
    limit: `<= ${String(MAX_MAPLIBRE_GZIP_BYTES)} B`,
    pass: lazy.maplibreFiles > 0 && lazy.maplibreGzipBytes <= MAX_MAPLIBRE_GZIP_BYTES,
  });
  gates.push({
    gate: "copies of MapLibre's shared module downloaded",
    value: lazy.sharedModuleCopies,
    limit: '1',
    pass: lazy.sharedModuleCopies === 1,
  });

  const pass = gates.every((g) => g.pass);
  const report = {
    generatedAt: new Date().toISOString(),
    url: URL_UNDER_TEST,
    environment: {
      lighthouse: await lighthouseVersion(),
      chrome: chromeVersion(),
      chromeFlags: CHROME_FLAGS,
      webglRenderer: await webglRenderer(),
      cpus: os.cpus().length,
      cpuModel: os.cpus()[0]?.model ?? 'unknown',
      benchmarkIndex: median(allRuns.map((r) => r.benchmarkIndex)),
      runsPerPreset: RUNS,
    },
    presets: {
      mobile: { throttling: 'simulated slow 4G, 4x CPU', median: mobile, runs: results.mobile },
      desktop: { throttling: 'simulated desktop dense 4G', median: desktop, runs: results.desktop },
      devtools4g: { throttling: 'applied (devtools) slow 4G, 4x CPU', runs: results.devtools4g },
    },
    consoleErrors,
    foreignRequests: foreign,
    lazyScripts: lazy,
    gates,
    pass,
  };
  // Formatted as "npm run format" would, so the committed report passes format:check.
  const prettierConfig = (await prettier.resolveConfig(REPORT)) ?? {};
  await writeFile(
    REPORT,
    await prettier.format(JSON.stringify(report), { ...prettierConfig, filepath: REPORT }),
  );

  for (const g of gates) {
    process.stdout.write(
      `${g.pass ? 'pass' : 'FAIL'}  ${g.gate}: ${String(g.value)} (${g.limit})\n`,
    );
  }
  process.stdout.write(
    `perf: wrote perf/lighthouse.json, ${pass ? 'all gates pass' : 'gate failed'}\n`,
  );
  if (!pass) process.exitCode = 1;
}

await main();

#!/usr/bin/env node
// @ts-check
/**
 * Builds the search index the site's search worker loads.
 *
 * Input: JSON Lines files, one record per line, in any of three shapes:
 *
 *   search record  {"kind":"school"|"district"|"city"|"zip","id","name","sub",
 *                   "state","lat","lon","weight"}   (see src/search/types.ts)
 *   city           {"geoid","name","kind","state","lat","lon","population"}
 *                   as `snowlight places build` writes cities.jsonl
 *   ZIP code       {"zcta","states","lat","lon","districts"}
 *                   as `snowlight places build` writes zips.jsonl
 *
 * Cities become search records with the state's name as their second line
 * and their population (0 when the source has none) as weight. ZIP codes
 * become records named by their code, with their states' names as the second
 * line and weight 0, so they rank by code. Nothing else is added or guessed.
 *
 * Output: one gzip-compressed index file (layout in src/search/format.ts),
 * byte-identical for identical input.
 *
 *   node scripts/build-search-index.mjs [--out FILE] [--check] [--json] [INPUT.jsonl | DIR]...
 *
 * With no inputs it reads every .jsonl file in ../pipeline/out/site-data/search.
 * --out defaults to ../pipeline/out/site-data/search-index.bin.
 * --check builds in memory and exits 1 if --out differs.
 */
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { registerHooks } from 'node:module';
import { dirname, join, relative, resolve } from 'node:path';
import process from 'node:process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

// The index code is TypeScript shared with the site. Node strips its types;
// this hook lets its extensionless relative imports resolve to .ts files.
registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (/^\.\.?\//.test(specifier) && !/\.[cm]?[jt]s$/.test(specifier)) {
        return nextResolve(`${specifier}.ts`, context);
      }
      throw error;
    }
  },
});

// Imported after the hook is in place, so not as static imports.
const { RecordError, encodeIndex, validateRecord } = await import('../src/search/encode.ts');
const { STATES, STATE_INDEX } = await import('../src/search/states.ts');

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const DEFAULT_IN = resolve(web, '../pipeline/out/site-data/search');
const DEFAULT_OUT = resolve(web, '../pipeline/out/site-data/search-index.bin');

/** @typedef {import('../src/search/types.ts').SearchRecord} SearchRecord */

const stateNames = new Map(STATES.map(([code, name]) => [code, name]));

/**
 * @param {unknown} value
 * @param {string} where
 * @returns {Record<string, unknown>}
 */
function asObject(value, where) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new RecordError(where, 'expected a JSON object');
  }
  return /** @type {Record<string, unknown>} */ (value);
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} where
 * @returns {SearchRecord}
 */
function fromCity(obj, where) {
  const { geoid, name, state, lat, lon, population } = obj;
  if (typeof geoid !== 'string' || !/^\d{7}$/.test(geoid)) {
    throw new RecordError(where, 'city geoid must be 7 digits');
  }
  if (typeof state !== 'string' || !STATE_INDEX.has(state)) {
    throw new RecordError(where, 'city state must be a USPS code');
  }
  if (population !== null && (typeof population !== 'number' || population < 0)) {
    throw new RecordError(where, 'city population must be a number or null');
  }
  return validateRecord(
    {
      kind: 'city',
      id: geoid,
      name,
      sub: stateNames.get(state) ?? state,
      state,
      lat,
      lon,
      weight: population ?? 0,
    },
    where,
  );
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} where
 * @returns {SearchRecord}
 */
function fromZip(obj, where) {
  const { zcta, states, lat, lon } = obj;
  if (typeof zcta !== 'string' || !/^\d{5}$/.test(zcta)) {
    throw new RecordError(where, 'zcta must be 5 digits');
  }
  if (
    !Array.isArray(states) ||
    states.length === 0 ||
    !states.every((s) => typeof s === 'string' && STATE_INDEX.has(s))
  ) {
    throw new RecordError(where, 'states must be a non-empty list of USPS codes');
  }
  const codes = /** @type {string[]} */ (states);
  return validateRecord(
    {
      kind: 'zip',
      id: zcta,
      name: zcta,
      sub: codes.map((s) => stateNames.get(s) ?? s).join(', '),
      state: codes[0],
      lat,
      lon,
      weight: 0,
    },
    where,
  );
}

/**
 * @param {unknown} value
 * @param {string} where
 * @returns {SearchRecord}
 */
function toRecord(value, where) {
  const obj = asObject(value, where);
  if ('zcta' in obj) return fromZip(obj, where);
  if ('geoid' in obj) return fromCity(obj, where);
  return validateRecord(obj, where);
}

/**
 * @param {string} file
 * @param {SearchRecord[]} out
 */
async function readJsonLines(file, out) {
  const name = shortPath(file);
  const lines = createInterface({ input: createReadStream(file, 'utf8'), crlfDelay: Infinity });
  let n = 0;
  for await (const line of lines) {
    n++;
    if (line.trim().length === 0) continue;
    const where = `${name}:${String(n)}`;
    /** @type {unknown} */
    let value;
    try {
      value = JSON.parse(line);
    } catch (error) {
      throw new RecordError(where, `not valid JSON (${String(error)})`);
    }
    out.push(toRecord(value, where));
  }
}

/** @param {string[]} argv */
function parseArgs(argv) {
  /** @type {{ out: string, check: boolean, json: boolean, inputs: string[] }} */
  const args = { out: DEFAULT_OUT, check: false, json: false, inputs: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i] ?? '';
    if (a === '--out') {
      const value = argv[++i];
      if (!value) throw new Error('--out needs a file path');
      args.out = resolve(value);
    } else if (a === '--check') args.check = true;
    else if (a === '--json') args.json = true;
    else if (a === '--help' || a === '-h') {
      process.stdout.write(
        'usage: build-search-index.mjs [--out FILE] [--check] [--json] [INPUT.jsonl | DIR]...\n',
      );
      process.exit(0);
    } else if (a.startsWith('--')) throw new Error(`unknown option ${a}`);
    else args.inputs.push(resolve(a));
  }
  if (args.inputs.length === 0) args.inputs.push(DEFAULT_IN);
  return args;
}

/** @param {string[]} inputs */
async function inputFiles(inputs) {
  /** @type {string[]} */
  const files = [];
  for (const input of inputs) {
    const info = await stat(input);
    if (info.isDirectory()) {
      const names = (await readdir(input)).filter((f) => f.endsWith('.jsonl')).sort();
      if (names.length === 0) throw new Error(`no .jsonl files in ${input}`);
      files.push(...names.map((f) => join(input, f)));
    } else files.push(input);
  }
  return files;
}

/** A path relative to the working directory when it is inside it. */
function shortPath(/** @type {string} */ path) {
  const rel = relative(process.cwd(), path);
  return rel.startsWith('..') ? path : rel;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const files = await inputFiles(args.inputs);
  /** @type {SearchRecord[]} */
  const records = [];
  for (const file of files) await readJsonLines(file, records);
  if (records.length === 0) throw new Error('no records to index');

  const { bytes, stats } = encodeIndex(records);
  const gz = gzipSync(bytes, { level: 9 });
  const sha256 = createHash('sha256').update(gz).digest('hex');
  const summary = {
    out: args.out,
    inputs: files,
    ...stats,
    gzipBytes: gz.length,
    sha256,
  };

  if (args.check) {
    /** @type {Buffer | null} */
    const current = await readFile(args.out).catch(() => null);
    if (!current?.equals(gz)) {
      process.stderr.write(`${args.out} is stale; run npm run build:search\n`);
      process.exit(1);
    }
  } else {
    await mkdir(dirname(args.out), { recursive: true });
    await writeFile(args.out, gz);
  }

  if (args.json) process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
  else {
    const kinds = Object.entries(stats.byKind)
      .map(([k, v]) => `${String(v)} ${k}`)
      .join(', ');
    process.stdout.write(
      `${args.check ? 'checked' : 'wrote'} ${shortPath(args.out)}: ` +
        `${String(stats.records)} records (${kinds}), ${String(stats.tokens)} tokens, ` +
        `${(gz.length / 1e6).toFixed(2)} MB gzip (${(stats.bytes / 1e6).toFixed(2)} MB raw), ` +
        `sha256 ${sha256.slice(0, 16)}\n`,
    );
  }
}

main().catch((/** @type {unknown} */ error) => {
  process.stderr.write(
    `build-search-index: ${error instanceof Error ? error.message : String(error)}\n`,
  );
  process.exit(1);
});

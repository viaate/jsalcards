#!/usr/bin/env node
// @ts-check
/**
 * Stages the pipeline's outputs as the site's data: "npm run stage".
 *
 * Reads what the pipeline wrote and puts the site's data in public/data/,
 * which Vite serves in dev and preview and copies into every build as data/
 * (tools/data-files.ts lists it for the page). Staging again replaces the
 * folder whole, so it only ever holds one staging. Nothing is made up and
 * nothing is filled in: a missing or inconsistent input stops the staging.
 *
 * Needs (the README at the repository root has the commands):
 *
 *   pipeline/out/site-data/schools/      meta.json, points.bin, schools.pmtiles
 *                                        (snowlight directory build)
 *   pipeline/out/internal/directory/     schools.parquet, districts.parquet
 *                                        (the same build's own tables)
 *   pipeline/out/site-data/search/       cities.jsonl, zips.jsonl
 *                                        (snowlight places build)
 *   uv, to read the tables with the pipeline's environment
 *
 * Writes public/data/:
 *
 *   schools/meta.<hash>.json          the directory, as the pipeline wrote it
 *   schools/points.<hash>.bin
 *   schools/schools.<hash>.pmtiles
 *   search-index.<hash>.bin           built by scripts/build-search-index.mjs from
 *                                     the directory's schools and districts and
 *                                     the places build's cities and ZIP codes
 *   everything else the pipeline published under site-data (live/, and any
 *   predictions/, stats/, replays/ or track-record.json), as written
 *
 * <hash> is the first 10 hex digits of the file's SHA-256 (src/data/paths.ts):
 * those files can be cached for good, and a new staging gets new names. The
 * pipeline's own records (*.internal.json) and hidden files are never staged;
 * the search index's inputs are not published themselves.
 *
 * Search records, one per school and district of the directory:
 *
 *   school    its NCES id and name (meta.json), where it is (points.bin), its
 *             town and state as NCES lists them ("Kansas City, MO"), and its
 *             enrollment as weight (0 where NCES reports none)
 *   district  its NCES id and name, its office's town, state and place, and
 *             its schools' enrollment together as weight; a district that is
 *             one school of the same name (most charter schools) is found as
 *             that school
 *
 * Each also carries its name as the page shows it (src/text/names.ts, with
 * the directory's fixes, src/text/school-names.ts) where that reads with
 * words the written name is not found by, or with more or fewer of them:
 * "MIDDLE SCHOOL" of Citizens of the World Charter is also found as "Citizens
 * of the World Charter - Middle School", and "ALLEN VILLAGE ELEMENTARY ACADE"
 * as "Allen Village Elementary Academy". Staging again after the name rules
 * change keeps the two in step.
 *
 *   node scripts/stage-data.mjs [--site DIR] [--internal DIR] [--pipeline DIR] [--to DIR]
 */
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { registerHooks } from 'node:module';
import { tmpdir } from 'node:os';
import { basename, dirname, join, relative, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

// The site's own TypeScript modules; this hook lets their extensionless relative imports resolve.
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

const { casedName, displayName } = await import('../src/text/names.ts');
const { nameFixes, stateOfId } = await import('../src/text/school-names.ts');
const { hashedPath } = await import('../src/data/paths.ts');
const { STATE_INDEX } = await import('../src/search/states.ts');
const { canonicalLength, indexTokens, tokenize } = await import('../src/search/normalize.ts');

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** The directory files, as the pipeline names them under site-data. */
const META = 'schools/meta.json';
const POINTS = 'schools/points.bin';
const TILES = 'schools/schools.pmtiles';
/** The places build's records, which go into the search index. */
const SEARCH_INPUTS = ['search/cities.jsonl', 'search/zips.jsonl'];
/** The search index, as the page asks for it. */
const SEARCH_INDEX = 'search-index.bin';
/** Under site-data, what staging handles itself rather than copying as written. */
const HANDLED = new Set([META, POINTS, TILES, ...SEARCH_INPUTS, SEARCH_INDEX]);

/** The directory build's record of what it wrote (never published). */
const MANIFEST = 'schools/manifest.internal.json';

/** points.bin (pipeline/snowlight/directory/points.py; src/data/directory.ts). */
const POINTS_MAGIC = 'SLPT';
const POINTS_HEADER = 16;
const POINTS_RECORD = 13;
const NO_DISTRICT = 0xffffffff;

class StageError extends Error {}

/** @param {string[]} argv */
function parseArgs(argv) {
  const args = {
    site: resolve(WEB, '../pipeline/out/site-data'),
    internal: resolve(WEB, '../pipeline/out/internal/directory'),
    pipeline: resolve(WEB, '../pipeline'),
    to: resolve(WEB, 'public/data'),
  };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i] ?? '';
    const key = flag.replace(/^--/, '');
    if (flag === '--help' || flag === '-h') {
      process.stdout.write(
        'usage: stage-data.mjs [--site DIR] [--internal DIR] [--pipeline DIR] [--to DIR]\n',
      );
      process.exit(0);
    }
    if (!(key in args) || !flag.startsWith('--')) throw new StageError(`unknown option ${flag}`);
    const value = argv[++i];
    if (value === undefined || value === '') throw new StageError(`${flag} needs a folder`);
    args[/** @type {keyof typeof args} */ (key)] = resolve(value);
  }
  return args;
}

/** A path relative to the working directory when it is inside it. */
function shortPath(/** @type {string} */ path) {
  const rel = relative(process.cwd(), path);
  return rel.startsWith('..') ? path : rel;
}

/** @param {string} file */
function need(file) {
  if (!existsSync(file)) throw new StageError(`${shortPath(file)} is missing`);
  return file;
}

/** @param {Buffer} bytes */
function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

/**
 * @typedef {{ ids: string[], names: string[], count: number,
 *   districts: { ids: string[], names: string[] } }} Meta
 */

/** @param {string} file @returns {Meta} */
function readMeta(file) {
  /** @type {any} */
  const meta = JSON.parse(readFileSync(file, 'utf8'));
  const strings = (/** @type {unknown} */ list, /** @type {number} */ length) =>
    Array.isArray(list) && list.length === length && list.every((s) => typeof s === 'string');
  if (meta?.schema_version !== 1) throw new StageError(`${META}: not schema version 1`);
  if (!Number.isSafeInteger(meta.count) || meta.count <= 0) {
    throw new StageError(`${META}: no schools`);
  }
  if (!strings(meta.ids, meta.count) || !strings(meta.names, meta.count)) {
    throw new StageError(`${META}: ids and names do not match the count`);
  }
  const districts = meta.districts ?? {};
  if (!Array.isArray(districts.ids) || !strings(districts.names, districts.ids.length)) {
    throw new StageError(`${META}: district ids and names do not match`);
  }
  return meta;
}

/**
 * Each school's place and district, from points.bin.
 * @param {Buffer} bytes @param {Meta} meta
 */
function readPoints(bytes, meta) {
  const districts = meta.districts.ids.length;
  if (
    bytes.length < POINTS_HEADER ||
    bytes.toString('latin1', 0, 4) !== POINTS_MAGIC ||
    bytes.readUInt16LE(4) !== 1 ||
    bytes.readUInt16LE(6) !== POINTS_RECORD ||
    bytes.readUInt32LE(8) !== meta.count ||
    bytes.readUInt32LE(12) !== districts ||
    bytes.length !== POINTS_HEADER + POINTS_RECORD * meta.count
  ) {
    throw new StageError(`${POINTS}: not the points of ${META}`);
  }
  const lon = new Float64Array(meta.count);
  const lat = new Float64Array(meta.count);
  const district = new Int32Array(meta.count);
  for (let i = 0; i < meta.count; i++) {
    const at = POINTS_HEADER + POINTS_RECORD * i;
    lon[i] = bytes.readInt32LE(at) / 1e6;
    lat[i] = bytes.readInt32LE(at + 4) / 1e6;
    const index = bytes.readUInt32LE(at + 8);
    if (index !== NO_DISTRICT && index >= districts) {
      throw new StageError(`${POINTS}: school ${String(i)} points past the districts`);
    }
    district[i] = index === NO_DISTRICT ? -1 : index;
  }
  return { lon, lat, district };
}

/**
 * Checks the directory files against the build's own record of them, when it
 * kept one: a file changed or swapped since is not the build's output.
 * @param {string} site @param {Record<string, Buffer>} files by path under site-data
 */
function checkManifest(site, files) {
  const file = join(site, MANIFEST);
  if (!existsSync(file)) return;
  /** @type {{ outputs?: Record<string, { sha256?: unknown }> }} */
  const manifest = JSON.parse(readFileSync(file, 'utf8'));
  for (const [path, bytes] of Object.entries(files)) {
    const recorded = manifest.outputs?.[basename(path)]?.sha256;
    if (recorded !== undefined && recorded !== sha256(bytes)) {
      throw new StageError(`${path} is not the file the directory build wrote (${MANIFEST})`);
    }
  }
}

/** @param {string} file */
function checkTiles(file) {
  const bytes = readFileSync(file);
  // PMTiles version 3, vector tiles (src/map/basemap/mask/pmtiles.ts reads them).
  if (
    bytes.length < 127 ||
    bytes.toString('latin1', 0, 7) !== 'PMTiles' ||
    bytes[7] !== 3 ||
    bytes[99] !== 1
  ) {
    throw new StageError(`${TILES}: not a PMTiles v3 vector tileset`);
  }
  return bytes;
}

/**
 * The directory's own columns, read with the pipeline's environment (scripts/directory-rows.py).
 * @param {{ internal: string, pipeline: string }} args @param {string} work
 */
function readTables(args, work) {
  need(join(args.internal, 'schools.parquet'));
  need(join(args.internal, 'districts.parquet'));
  const out = join(work, 'rows');
  const run = spawnSync(
    'uv',
    [
      'run',
      '--frozen',
      '--project',
      args.pipeline,
      'python',
      join(WEB, 'scripts/directory-rows.py'),
      '--internal',
      args.internal,
      '--out',
      out,
    ],
    { encoding: 'utf8' },
  );
  if (run.error !== undefined) {
    throw new StageError(`could not run uv to read the directory's tables: ${run.error.message}`);
  }
  if (run.status !== 0) {
    throw new StageError(`reading the directory's tables failed:\n${run.stderr.trim()}`);
  }
  /** @param {string} name */
  const rows = (name) =>
    readFileSync(join(out, name), 'utf8')
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => /** @type {Record<string, unknown>} */ (JSON.parse(line)));
  return { schools: rows('schools.jsonl'), districts: rows('districts.jsonl') };
}

/** @param {unknown} value */
const isText = (value) => typeof value === 'string' && value.trim() !== '';

/**
 * "Kansas City, MO": the town as NCES lists it, in the page's case, and the state.
 * @param {unknown} city @param {string} state
 */
const townOf = (city, state) => `${casedName(String(city).trim())}, ${state}`;

/**
 * The name a school or district is shown by, when search needs it: when it
 * has a word the written name is not found by, or a different number of
 * words (search.ts SearchRecord.shown). Otherwise undefined.
 * @param {string} id @param {string} name @param {import('../src/text/names.ts').NameFix | undefined} fix
 */
function shownFor(id, name, fix) {
  const shown = displayName(name, { state: stateOfId(id) }, fix ?? {});
  const written = tokenize(name);
  const found = new Set(indexTokens(written));
  const words = tokenize(shown);
  const differs =
    words.some((word) => !found.has(word)) || canonicalLength(words) !== canonicalLength(written);
  return differs ? shown : undefined;
}

/** Whitespace and case aside, whether two names are the same. */
const sameName = (/** @type {string} */ a, /** @type {string} */ b) =>
  a.trim().replace(/\s+/g, ' ').toUpperCase() === b.trim().replace(/\s+/g, ' ').toUpperCase();

/**
 * Search records for the directory's schools and districts.
 * @param {Meta} meta
 * @param {ReturnType<typeof readPoints>} points
 * @param {ReturnType<typeof readTables>} tables
 */
function directoryRecords(meta, points, tables) {
  const { schools, districts } = tables;
  if (schools.length !== meta.count || districts.length !== meta.districts.ids.length) {
    throw new StageError(
      `the directory's tables (${String(schools.length)} schools, ${String(districts.length)} ` +
        `districts) are not those of ${META}; build the directory again`,
    );
  }
  // The names the page shows another way: cut off by NCES, or only generic words.
  const fixes = nameFixes({
    ids: meta.ids,
    names: meta.names,
    districtOf: points.district,
    districts: meta.districts,
  });
  const enrollment = new Float64Array(districts.length);
  const members = new Int32Array(districts.length);
  /** The school each district has, while it has only one. */
  const onlySchool = new Int32Array(districts.length).fill(-1);
  const schoolRecords = schools.map((row, i) => {
    const id = meta.ids[i] ?? '';
    if (row.index !== i || row.id !== id) {
      throw new StageError(`school ${String(i)} (${id}) is not in the tables' place ${String(i)}`);
    }
    const state = String(row.state);
    if (!STATE_INDEX.has(state) || !isText(row.city)) {
      throw new StageError(`school ${id} has no town or state`);
    }
    const students = row.enrollment ?? 0;
    if (typeof students !== 'number' || !Number.isFinite(students) || students < 0) {
      throw new StageError(`school ${id} has enrollment ${String(row.enrollment)}`);
    }
    const district = points.district[i] ?? -1;
    if (district >= 0) {
      enrollment[district] = (enrollment[district] ?? 0) + students;
      members[district] = (members[district] ?? 0) + 1;
      onlySchool[district] = i;
    }
    const name = meta.names[i] ?? '';
    const shown = shownFor(id, name, fixes.schools[id]);
    return {
      kind: 'school',
      id,
      name,
      ...(shown === undefined ? {} : { shown }),
      sub: townOf(row.city, state),
      state,
      lat: points.lat[i] ?? 0,
      lon: points.lon[i] ?? 0,
      weight: students,
    };
  });
  let merged = 0;
  const districtRecords = [];
  for (const [d, row] of districts.entries()) {
    const id = meta.districts.ids[d] ?? '';
    const name = meta.districts.names[d] ?? '';
    if (row.index !== d || row.id !== id) {
      throw new StageError(
        `district ${String(d)} (${id}) is not in the tables' place ${String(d)}`,
      );
    }
    const state = String(row.state);
    const { lat, lon } = row;
    if (!STATE_INDEX.has(state) || !isText(row.city)) {
      throw new StageError(`district ${id} has no town or state`);
    }
    if (typeof lat !== 'number' || typeof lon !== 'number') {
      throw new StageError(`district ${id} has no place`);
    }
    const only = members[d] === 1 ? (onlySchool[d] ?? -1) : -1;
    if (only >= 0 && sameName(meta.names[only] ?? '', name)) {
      merged++;
      continue;
    }
    const shown = shownFor(id, name, fixes.districts[id]);
    districtRecords.push({
      kind: 'district',
      id,
      name,
      ...(shown === undefined ? {} : { shown }),
      sub: townOf(row.city, state),
      state,
      lat,
      lon,
      weight: enrollment[d] ?? 0,
    });
  }
  return { schoolRecords, districtRecords, merged };
}

/** @param {string} file @param {readonly object[]} records */
function writeJsonLines(file, records) {
  writeFileSync(file, records.map((record) => JSON.stringify(record)).join('\n') + '\n');
}

/**
 * Every file under `root`, as sorted POSIX paths relative to it.
 * @param {string} root @param {string} [prefix]
 * @returns {string[]}
 */
function filesUnder(root, prefix = '') {
  return readdirSync(join(root, prefix), { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory()
        ? filesUnder(root, `${prefix}${entry.name}/`)
        : entry.isFile()
          ? [`${prefix}${entry.name}`]
          : [],
    )
    .sort();
}

/** Whether a file under site-data is published (tools/data-files.ts isPublished, per name). */
const published = (/** @type {string} */ path) =>
  path.split('/').every((name) => !name.startsWith('.') && !name.endsWith('.internal.json'));

/** Refuses to empty a folder that does not look like a data folder. @param {string} to */
function clear(to) {
  if (existsSync(to)) {
    const empty = readdirSync(to).length === 0;
    if (!empty && basename(to) !== 'data') {
      throw new StageError(`${shortPath(to)} is not empty and not a data folder; not replacing it`);
    }
    rmSync(to, { recursive: true, force: true });
  }
  mkdirSync(to, { recursive: true });
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const work = mkdtempSync(join(tmpdir(), 'snowlight-stage-'));
  try {
    const metaBytes = readFileSync(need(join(args.site, META)));
    const pointsBytes = readFileSync(need(join(args.site, POINTS)));
    const tilesBytes = checkTiles(need(join(args.site, TILES)));
    for (const input of SEARCH_INPUTS) need(join(args.site, input));
    checkManifest(args.site, { [META]: metaBytes, [POINTS]: pointsBytes, [TILES]: tilesBytes });

    const meta = readMeta(join(args.site, META));
    const points = readPoints(pointsBytes, meta);
    const tables = readTables(args, work);
    const { schoolRecords, districtRecords, merged } = directoryRecords(meta, points, tables);
    const schoolsFile = join(work, 'schools.jsonl');
    const districtsFile = join(work, 'districts.jsonl');
    writeJsonLines(schoolsFile, schoolRecords);
    writeJsonLines(districtsFile, districtRecords);

    const indexFile = join(work, SEARCH_INDEX);
    const built = spawnSync(
      process.execPath,
      [
        join(WEB, 'scripts/build-search-index.mjs'),
        '--json',
        '--out',
        indexFile,
        schoolsFile,
        districtsFile,
        ...SEARCH_INPUTS.map((input) => join(args.site, input)),
      ],
      { encoding: 'utf8' },
    );
    if (built.status !== 0) throw new StageError(`search index: ${built.stderr.trim()}`);

    clear(args.to);
    /** @type {[string, number][]} */
    const staged = [];
    /** @param {string} path @param {Buffer} bytes */
    const putHashed = (path, bytes) => {
      const name = hashedPath(path, sha256(bytes));
      mkdirSync(dirname(join(args.to, name)), { recursive: true });
      writeFileSync(join(args.to, name), bytes);
      staged.push([name, bytes.length]);
    };
    putHashed(META, metaBytes);
    putHashed(POINTS, pointsBytes);
    putHashed(TILES, tilesBytes);
    putHashed(SEARCH_INDEX, readFileSync(indexFile));
    for (const path of filesUnder(args.site)) {
      if (HANDLED.has(path) || path.startsWith('search/') || !published(path)) continue;
      mkdirSync(dirname(join(args.to, path)), { recursive: true });
      copyFileSync(join(args.site, path), join(args.to, path));
      staged.push([path, statSync(join(args.to, path)).size]);
    }

    staged.sort((a, b) => (a[0] < b[0] ? -1 : 1));
    const lines = staged.map(
      ([name, size]) => `  ${name.padEnd(44)} ${(size / 1e6).toFixed(2).padStart(7)} MB`,
    );
    /** @type {{ records: number, byKind: Record<string, number> }} */
    const index = JSON.parse(built.stdout);
    const kinds = Object.entries(index.byKind)
      .map(([kind, count]) => `${String(count)} ${kind}`)
      .join(', ');
    process.stdout.write(
      `staged ${shortPath(args.to)}:\n${lines.join('\n')}\n` +
        `search index: ${String(index.records)} records (${kinds}); ` +
        `${String(merged)} one-school districts are found as their school\n`,
    );
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(
    `stage-data: ${error instanceof Error ? error.message : String(error)}\n` +
      (error instanceof StageError ? '' : `${String(error instanceof Error ? error.stack : '')}\n`),
  );
  process.exit(1);
}

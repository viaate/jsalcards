// gen-golden.mjs: the iPhone app's golden answers, made by running the site's own code.
//
//   node ios/tools/gen-golden.mjs            write the golden files
//   node ios/tools/gen-golden.mjs --check    write nothing; compare with what is committed
//
// It imports the site's modules (web/src) through node-hooks.mjs, runs each family's
// cases, and writes ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/golden/<family>.json.
// The Swift tests must give the same answers, character for character.
//
// Every answer comes from the site's code. This script never builds a sentence itself.
//
// A golden file is
//   {"family", "min_cases", "made_from": [{"path", "sha256"} for each site file loaded],
//    "cases": [one case per line]}
// written with sorted keys, ASCII only, a fixed order and no time stamp, so two runs give
// the same bytes on any machine and in any time zone.
//
// --check compares answers, not files: `family`, `min_cases` and `cases`. A site file whose
// bytes changed while every answer stayed the same (a comment, say) is printed as a note
// and fails nothing.
//
// Exit codes:
//   0  everything matches (or, when writing, everything was written)
//   1  an answer differs from the committed golden files, or a family is below its minimum
//   2  the site's code could not be loaded or run
//   3  Node is older than 22.18, or the arguments are wrong
//   4  a site file that was loaded lies outside what the words watch covers
//
// Node's built-in modules only: it needs no `npm ci`.

// A site function that leaned on the machine's time zone must show up as a difference, so
// this never runs on a UTC clock. CI runs it under two odd zones.
if (process.env.TZ === undefined || process.env.TZ === '' || process.env.TZ === 'UTC') {
  process.env.TZ = 'America/St_Johns';
}

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const EXIT_DIFFERS = 1;
const EXIT_CANNOT_LOAD = 2;
const EXIT_USAGE = 3;
const EXIT_OUTSIDE_WATCH = 4;

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');
const GOLDEN = join(REPO, 'ios', 'SnowlightCore', 'Tests', 'SnowlightCoreTests', 'Fixtures', 'golden');

/**
 * What the words watch (.github/workflows/ios-words-watch.yml) covers. A site file loaded
 * from anywhere else could change without the watch running, so that is refused.
 */
const WATCHED_FOLDER = 'web/src/';
const WATCHED_FILES = ['web/scripts/check-copy.mjs'];

/**
 * The families. `modules` are the site modules a family calls, named from web/src.
 * `cases` gets those modules, keyed by the same names, and returns the cases in a fixed
 * order: each case is one input with the site's answer to it.
 */
const FAMILIES = [
  {
    // The site's fixed words, as they are.
    family: 'copy',
    minCases: 1,
    modules: ['copy.ts', 'copy-details.ts', 'copy-chance.ts'],
    cases: (site) => [
      {
        copy: site['copy.ts'].copy,
        detailsCopy: site['copy-details.ts'].detailsCopy,
        chanceCopy: { noSchool: site['copy-chance.ts'].chanceCopy.noSchool },
      },
    ],
  },
];

class Stop extends Error {
  /**
   * @param {number} code
   * @param {string} message
   */
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function say(line) {
  process.stdout.write(`${line}\n`);
}

/** A repository path with forward slashes, whatever the machine. */
function repoPath(absolute) {
  return relative(REPO, absolute).split(sep).join('/');
}

function nodeIsNewEnough() {
  const [major, minor] = process.versions.node.split('.').map((part) => Number(part));
  return major > 22 || (major === 22 && minor >= 18);
}

// Writing ------------------------------------------------------------------------------

/** A JSON string in ASCII: everything outside it is written as a \u escape. */
function quote(text) {
  return JSON.stringify(text).replace(
    /[\u007f-\uffff]/g,
    (unit) => `\\u${unit.charCodeAt(0).toString(16).padStart(4, '0')}`,
  );
}

/**
 * One value as JSON on one line, with sorted keys. Refuses what JSON cannot hold: a
 * golden answer is null, true, false, a finite number, a string, a list or a plain object.
 * @param {unknown} value
 * @param {string} where
 * @returns {string}
 */
function canonical(value, where) {
  if (value === null) return 'null';
  if (typeof value === 'string') return quote(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Stop(EXIT_CANNOT_LOAD, `${where} is ${value}, which JSON cannot hold`);
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, index) => canonical(item, `${where}[${index}]`)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const kind = Object.getPrototypeOf(value);
    if (kind !== Object.prototype && kind !== null) {
      throw new Stop(EXIT_CANNOT_LOAD, `${where} is not a plain object`);
    }
    const keys = Object.keys(value).sort();
    return `{${keys.map((key) => `${quote(key)}:${canonical(value[key], `${where}.${key}`)}`).join(',')}}`;
  }
  throw new Stop(EXIT_CANNOT_LOAD, `${where} is a ${typeof value}, which a golden file cannot hold`);
}

/** The whole text of a golden file. */
function fileText(made) {
  const lines = [`{"family": ${quote(made.family)}, "min_cases": ${made.minCases}, "made_from": [`];
  made.madeFrom.forEach((source, index) => {
    const comma = index < made.madeFrom.length - 1 ? ',' : '';
    lines.push(`{"path": ${quote(source.path)}, "sha256": ${quote(source.sha256)}}${comma}`);
  });
  lines.push('], "cases": [');
  made.caseLines.forEach((line, index) => {
    lines.push(line + (index < made.caseLines.length - 1 ? ',' : ''));
  });
  lines.push(']}');
  return `${lines.join('\n')}\n`;
}

// Loading the site's code ----------------------------------------------------------------

/**
 * Loads the site's modules and runs every family.
 * @returns {Promise<Array<{ family: string, minCases: number, madeFrom: Array<{ path: string, sha256: string }>, caseLines: string[] }>>}
 */
async function makeAll() {
  const { reported, siteRoot } = await import('./node-register.mjs');
  /** @type {Map<string, Set<string>>} which site file imports which */
  const imports = new Map();
  /** @type {Set<string>} */
  const loaded = new Set();
  const takeReports = () => {
    for (const message of reported()) {
      if (message.kind === 'load') loaded.add(message.path);
      if (message.kind === 'import') {
        if (!imports.has(message.from)) imports.set(message.from, new Set());
        imports.get(message.from).add(message.to);
      }
    }
  };

  const made = [];
  for (const spec of FAMILIES) {
    /** @type {Record<string, unknown>} */
    const site = {};
    for (const name of spec.modules) {
      const file = join(siteRoot, ...name.split('/'));
      try {
        site[name] = await import(pathToFileURL(file).href);
      } catch (error) {
        takeReports();
        throw new Stop(EXIT_CANNOT_LOAD, `${repoPath(file)}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    takeReports();

    let cases;
    try {
      cases = spec.cases(site);
    } catch (error) {
      throw new Stop(
        EXIT_CANNOT_LOAD,
        `the family '${spec.family}' could not be run: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    const caseLines = cases.map((one, index) => canonical(one, `${spec.family} case ${index}`));

    // Every site file this family's modules pulled in, found by following the imports.
    const files = new Set();
    const queue = spec.modules.map((name) => join(siteRoot, ...name.split('/')));
    while (queue.length > 0) {
      const file = queue.pop();
      if (files.has(file)) continue;
      files.add(file);
      for (const next of imports.get(file) ?? []) queue.push(next);
    }
    const madeFrom = [...files]
      .map((file) => ({
        path: repoPath(file),
        sha256: createHash('sha256').update(readFileSync(file)).digest('hex'),
      }))
      .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));

    made.push({ family: spec.family, minCases: spec.minCases, madeFrom, caseLines });
  }

  // Nothing may have been loaded from outside what the words watch covers.
  const outside = [...loaded]
    .map(repoPath)
    .filter((path) => !path.startsWith(WATCHED_FOLDER) && !WATCHED_FILES.includes(path))
    .sort();
  if (outside.length > 0) {
    throw new Stop(
      EXIT_OUTSIDE_WATCH,
      `loaded from outside ${WATCHED_FOLDER} and ${WATCHED_FILES.join(', ')}, which the words watch does not cover:\n  ${outside.join('\n  ')}`,
    );
  }
  return made;
}

// Checking -------------------------------------------------------------------------------

function shorten(text) {
  return text.length <= 300 ? text : `${text.slice(0, 300)}... (${text.length} characters)`;
}

/**
 * Where two JSON values first differ, as a path and the two values there; null when
 * they are the same.
 * @param {unknown} committed
 * @param {unknown} now
 * @param {string} path
 * @returns {{ path: string, committed: string, now: string } | null}
 */
function firstDifference(committed, now, path) {
  const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);
  if (Array.isArray(committed) && Array.isArray(now)) {
    for (let index = 0; index < Math.max(committed.length, now.length); index += 1) {
      const found = firstDifference(committed[index], now[index], `${path}[${index}]`);
      if (found !== null) return found;
    }
    return null;
  }
  if (isObject(committed) && isObject(now)) {
    for (const key of [...new Set([...Object.keys(committed), ...Object.keys(now)])].sort()) {
      const found = firstDifference(committed[key], now[key], path === '' ? key : `${path}.${key}`);
      if (found !== null) return found;
    }
    return null;
  }
  if (committed === now) return null;
  const show = (value) => (value === undefined ? '(nothing)' : shorten(JSON.stringify(value)));
  return { path: path === '' ? '(the whole case)' : path, committed: show(committed), now: show(now) };
}

/**
 * Compares what was made with what is committed. Prints what differs.
 * @returns {boolean} true when every answer matches
 */
function check(made) {
  let same = true;
  const wanted = new Set(made.map((one) => `${one.family}.json`));
  const present = existsSync(GOLDEN) ? readdirSync(GOLDEN).filter((name) => name.endsWith('.json')) : [];
  for (const name of present.sort()) {
    if (!wanted.has(name)) {
      say(`differs: golden/${name} is committed, and no family makes it`);
      same = false;
    }
  }

  for (const one of made) {
    const path = join(GOLDEN, `${one.family}.json`);
    if (!existsSync(path)) {
      say(`differs: ${one.family}: golden/${one.family}.json is not committed`);
      same = false;
      continue;
    }
    let committed;
    try {
      committed = JSON.parse(readFileSync(path, 'utf8'));
    } catch (error) {
      say(`differs: ${one.family}: the committed file does not parse (${error instanceof Error ? error.message : error})`);
      same = false;
      continue;
    }
    const committedSources = new Map(
      (Array.isArray(committed.made_from) ? committed.made_from : []).map((source) => [source.path, source.sha256]),
    );
    const changedSources = [];
    for (const source of one.madeFrom) {
      if (!committedSources.has(source.path)) changedSources.push(`${source.path} (now loaded)`);
      else if (committedSources.get(source.path) !== source.sha256) changedSources.push(source.path);
    }
    for (const path of committedSources.keys()) {
      if (!one.madeFrom.some((source) => source.path === path)) changedSources.push(`${path} (no longer loaded)`);
    }

    const problems = [];
    if (committed.family !== one.family) problems.push(`the file says family '${committed.family}'`);
    if (committed.min_cases !== one.minCases) {
      problems.push(`min_cases is ${committed.min_cases} in the file and ${one.minCases} in the generator`);
    }
    const committedCases = Array.isArray(committed.cases) ? committed.cases : [];
    const committedLines = committedCases.map((value, index) => canonical(value, `${one.family} committed case ${index}`));
    const most = Math.max(committedLines.length, one.caseLines.length);
    for (let index = 0; index < most; index += 1) {
      if (committedLines[index] !== one.caseLines[index]) {
        const where =
          committedLines[index] === undefined || one.caseLines[index] === undefined
            ? null
            : firstDifference(committedCases[index], JSON.parse(one.caseLines[index]), '');
        problems.push(
          where === null
            ? `case ${index} is the first that differs\n    committed: ${shorten(committedLines[index] ?? '(no such case)')}\n    the site now: ${shorten(one.caseLines[index] ?? '(no such case)')}`
            : `case ${index} is the first that differs, at ${where.path}\n    committed: ${where.committed}\n    the site now: ${where.now}`,
        );
        break;
      }
    }

    if (problems.length > 0) {
      same = false;
      say(`differs: ${one.family}: ${problems.join('; ')}`);
      if (changedSources.length > 0) {
        say(`  site files changed since this golden file was made:\n    ${changedSources.join('\n    ')}`);
      } else {
        say('  no site file this family loads has changed since the golden file was made');
      }
    } else {
      for (const path of changedSources) say(`note: ${path} changed, no answer changed`);
    }
  }
  return same;
}

// Main -----------------------------------------------------------------------------------

async function main(argv) {
  if (!nodeIsNewEnough()) {
    throw new Stop(EXIT_USAGE, `this needs Node 22.18 or newer to load the site's TypeScript; this is ${process.versions.node}`);
  }
  if (argv.length > 1 || (argv.length === 1 && argv[0] !== '--check')) {
    throw new Stop(EXIT_USAGE, 'usage: node ios/tools/gen-golden.mjs [--check]');
  }
  const checking = argv[0] === '--check';

  const made = await makeAll();
  for (const one of made) {
    say(`${one.family}: ${one.caseLines.length} cases`);
    if (one.caseLines.length < one.minCases) {
      throw new Stop(EXIT_DIFFERS, `the family '${one.family}' has ${one.caseLines.length} cases, below its minimum of ${one.minCases}`);
    }
  }

  if (checking) {
    if (!check(made)) {
      throw new Stop(
        EXIT_DIFFERS,
        "an answer of the site's code differs from the committed golden files. Make them again (node ios/tools/gen-golden.mjs) and update the Swift port",
      );
    }
    say(`golden: ${made.length} ${made.length === 1 ? 'family matches' : 'families match'} the site's code (zone ${process.env.TZ})`);
    return;
  }

  mkdirSync(GOLDEN, { recursive: true });
  const stale = readdirSync(GOLDEN).filter(
    (name) => name.endsWith('.json') && !made.some((one) => `${one.family}.json` === name),
  );
  if (stale.length > 0) {
    throw new Stop(EXIT_DIFFERS, `no family makes these files in golden/: ${stale.join(', ')}. Remove them`);
  }
  for (const one of made) writeFileSync(join(GOLDEN, `${one.family}.json`), fileText(one));
  say(`golden: wrote ${made.length} ${made.length === 1 ? 'file' : 'files'} (zone ${process.env.TZ})`);
}

try {
  await main(process.argv.slice(2));
} catch (error) {
  if (error instanceof Stop) {
    if (error.code === EXIT_CANNOT_LOAD) say("could not load the site's code");
    say(`gen-golden: ${error.message}`);
    process.exitCode = error.code;
  } else {
    // Anything unforeseen is a fault of this script or of the site's code under it, never
    // a changed word: it gets the loader's exit code, not the words message.
    say("could not load the site's code");
    say(`gen-golden: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}`);
    process.exitCode = EXIT_CANNOT_LOAD;
  }
}

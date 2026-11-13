// sync-fixtures.mjs: the pipeline's synthetic test files, copied byte for byte into the
// iPhone app's test fixtures, so the Swift tests read exactly what the pipeline and the site
// are tested with.
//
//   node ios/tools/sync-fixtures.mjs            copy them
//   node ios/tools/sync-fixtures.mjs --check    copy nothing; fail if a copy differs
//
// The copies sit in ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/site/, under the
// same names they have under pipeline/tests/. They are never edited by hand. Every school
// and district in them is made up.
//
// Exit codes:
//   0  every copy matches (or, when copying, every file was copied)
//   1  a copy differs from its source, is missing, or a file there is not one of the copies
//   3  wrong usage, or a source file is missing
//
// Node's built-in modules only: it needs no `npm ci`.

import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');
const SOURCE = join(REPO, 'pipeline', 'tests');
const TARGET = join(REPO, 'ios', 'SnowlightCore', 'Tests', 'SnowlightCoreTests', 'Fixtures', 'site');

/** The files copied, named from pipeline/tests/. `*` stands for every .json file in a folder. */
const FILES = [
  'schemas/examples/synthetic-closings.json',
  'schemas/examples/synthetic-predictions.json',
  'schemas/examples/synthetic-live-season.json',
  'schemas/examples/synthetic-directory-edition.json',
  'live/golden/*',
  'predict/golden/synthetic_predictions.json',
];

function say(line) {
  process.stdout.write(`${line}\n`);
}

/** Every file the list names, sorted, as paths under pipeline/tests/ with forward slashes. */
function wanted() {
  const names = [];
  for (const entry of FILES) {
    if (entry.endsWith('/*')) {
      const folder = entry.slice(0, -2);
      const found = readdirSync(join(SOURCE, ...folder.split('/')))
        .filter((name) => name.endsWith('.json'))
        .sort();
      if (found.length === 0) throw new Error(`no .json file in pipeline/tests/${folder}`);
      for (const name of found) names.push(`${folder}/${name}`);
    } else {
      names.push(entry);
    }
  }
  for (const name of names) {
    if (!existsSync(join(SOURCE, ...name.split('/')))) throw new Error(`pipeline/tests/${name} is missing`);
  }
  return names.sort();
}

/** Every file now under the copies' folder, as paths under it with forward slashes. */
function present(folder = TARGET) {
  if (!existsSync(folder)) return [];
  const names = [];
  for (const name of readdirSync(folder).sort()) {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) names.push(...present(path));
    else names.push(relative(TARGET, path).split(sep).join('/'));
  }
  return names;
}

function main(argv) {
  if (argv.length > 1 || (argv.length === 1 && argv[0] !== '--check')) {
    say('usage: node ios/tools/sync-fixtures.mjs [--check]');
    return 3;
  }
  const checking = argv[0] === '--check';
  let names;
  try {
    names = wanted();
  } catch (error) {
    say(`sync-fixtures: ${error instanceof Error ? error.message : String(error)}`);
    return 3;
  }

  const extra = present().filter((name) => !names.includes(name));
  if (checking) {
    let same = true;
    for (const name of names) {
      const source = readFileSync(join(SOURCE, ...name.split('/')));
      const copy = join(TARGET, ...name.split('/'));
      if (!existsSync(copy)) {
        say(`differs: site/${name} is missing (pipeline/tests/${name})`);
        same = false;
      } else if (!source.equals(readFileSync(copy))) {
        say(`differs: site/${name} is not a copy of pipeline/tests/${name}`);
        same = false;
      }
    }
    for (const name of extra) {
      say(`differs: site/${name} is not one of the copies`);
      same = false;
    }
    if (!same) {
      say('A shared fixture changed. Copy them again (node ios/tools/sync-fixtures.mjs), make the golden files again (node ios/tools/gen-golden.mjs) and update the Swift port.');
      return 1;
    }
    say(`fixtures: ${names.length} copies match the pipeline's files`);
    return 0;
  }

  for (const name of extra) rmSync(join(TARGET, ...name.split('/')));
  for (const name of names) {
    const copy = join(TARGET, ...name.split('/'));
    mkdirSync(dirname(copy), { recursive: true });
    writeFileSync(copy, readFileSync(join(SOURCE, ...name.split('/'))));
  }
  say(`fixtures: copied ${names.length} files${extra.length > 0 ? `, removed ${extra.length}` : ''}`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));

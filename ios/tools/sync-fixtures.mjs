// sync-fixtures.mjs: the pipeline's synthetic test files, copied byte for byte into the
// iPhone app's test fixtures, so the Swift tests read exactly what the pipeline and the site
// are tested with; and the picture tour's fixtures, written into the debug tour's code.
//
//   node ios/tools/sync-fixtures.mjs            copy them, and write the tour's file
//   node ios/tools/sync-fixtures.mjs --check    write nothing; fail if a copy or the
//                                               tour's file differs
//
// The copies sit in ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/site/, under the
// same names they have under pipeline/tests/. They are never edited by hand. Every school
// and district in them is made up.
//
// The tour's fixtures (M1 5.1) are the files in Fixtures/tour/, the source. The app holds no
// resource of them: ios/SnowlightKit/Sources/SnowlightKit/Tour/TourFixtures.swift holds each
// as the base64 text of its bytes, on one line in one literal, every line of code inside one
// `#if DEBUG` block, so a release build holds none of them (ios/tools/build.sh looks).
// That file is written here and never edited by hand.
//
// Exit codes:
//   0  every copy matches (or, when copying, every file was copied and the tour's written)
//   1  a copy differs from its source, is missing, or a file there is not one of the copies;
//      or the tour's file differs from what its fixtures make, or is missing
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
/** The tour's fixtures, the source (M1 5.1). */
const TOUR_SOURCE = join(REPO, 'ios', 'SnowlightCore', 'Tests', 'SnowlightCoreTests', 'Fixtures', 'tour');
/** The debug tour's file that holds them (M1 5.1). */
const TOUR_FILE = 'ios/SnowlightKit/Sources/SnowlightKit/Tour/TourFixtures.swift';

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

/** The tour's fixtures, by name (the file's name without .json), sorted. */
function tourFixtures() {
  if (!existsSync(TOUR_SOURCE)) throw new Error('ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/tour/ is missing');
  const names = readdirSync(TOUR_SOURCE)
    .filter((name) => name.endsWith('.json'))
    .sort();
  if (names.length === 0) throw new Error('no .json file in Fixtures/tour/');
  return names.map((file) => {
    const name = file.slice(0, -'.json'.length);
    if (!/^[a-z0-9-]+$/.test(name)) throw new Error(`Fixtures/tour/${file}: a fixture's name is lower-case letters, digits and hyphens only`);
    return { name, base64: readFileSync(join(TOUR_SOURCE, file)).toString('base64') };
  });
}

/** The text of Tour/TourFixtures.swift for these fixtures. */
function tourFile(fixtures) {
  const lines = [
    '// The picture tour\'s My School fixtures (M1 5.1). Debug builds only: nothing in this folder',
    '// exists in a release build, and no package holds the fixtures as a resource.',
    '//',
    '// Written by ios/tools/sync-fixtures.mjs from',
    '// ios/SnowlightCore/Tests/SnowlightCoreTests/Fixtures/tour/, the source: each fixture is the',
    '// base64 text of that file\'s bytes, on one line. Never edited by hand;',
    '// `node ios/tools/sync-fixtures.mjs --check` fails when this file differs from its fixtures.',
    '',
    '#if DEBUG',
    '',
    'import Foundation',
    '',
    '/// The tour\'s fixtures, each by the name -tour.fixture gives it.',
    'enum TourFixtures {',
    '    /// The bytes of the fixture of this name, or nil when there is none.',
    '    static func bytes(named name: String) -> Data? {',
    '        switch name {',
  ];
  for (const { name, base64 } of fixtures) {
    lines.push(`        case "${name}":`);
    lines.push(`            return Data(base64Encoded: "${base64}")`);
  }
  lines.push(
    '        default:',
    '            return nil',
    '        }',
    '    }',
    '}',
    '',
    '#endif',
  );
  return `${lines.join('\n')}\n`;
}

function main(argv) {
  if (argv.length > 1 || (argv.length === 1 && argv[0] !== '--check')) {
    say('usage: node ios/tools/sync-fixtures.mjs [--check]');
    return 3;
  }
  const checking = argv[0] === '--check';
  let names;
  let tour;
  try {
    names = wanted();
    tour = tourFile(tourFixtures());
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
    const tourPath = join(REPO, ...TOUR_FILE.split('/'));
    let tourSame = true;
    if (!existsSync(tourPath)) {
      say(`differs: ${TOUR_FILE} is missing`);
      tourSame = false;
    } else if (readFileSync(tourPath, 'utf8') !== tour) {
      say(`differs: ${TOUR_FILE} is not what Fixtures/tour/ makes`);
      tourSame = false;
    }
    if (!same) {
      say('A shared fixture changed. Copy them again (node ios/tools/sync-fixtures.mjs), make the golden files again (node ios/tools/gen-golden.mjs) and update the Swift port.');
    }
    if (!tourSame) {
      say(`The tour's fixtures and ${TOUR_FILE} differ. Write it again (node ios/tools/sync-fixtures.mjs); it is never edited by hand.`);
    }
    if (!same || !tourSame) return 1;
    say(`fixtures: ${names.length} copies match the pipeline's files; ${TOUR_FILE} matches Fixtures/tour/`);
    return 0;
  }

  for (const name of extra) rmSync(join(TARGET, ...name.split('/')));
  for (const name of names) {
    const copy = join(TARGET, ...name.split('/'));
    mkdirSync(dirname(copy), { recursive: true });
    writeFileSync(copy, readFileSync(join(SOURCE, ...name.split('/'))));
  }
  writeFileSync(join(REPO, ...TOUR_FILE.split('/')), tour);
  say(`fixtures: copied ${names.length} files${extra.length > 0 ? `, removed ${extra.length}` : ''}; wrote ${TOUR_FILE}`);
  return 0;
}

process.exitCode = main(process.argv.slice(2));
